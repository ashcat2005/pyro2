"""

The multigrid module provides a framework for solving elliptic
problems.  A multigrid object is just a list of grids, from the finest
mesh down (by factors of two) to a single interior zone (each grid has
the same number of guardcells).

The main multigrid class (MGcc) is setup to solve a constant-coefficient
Helmholtz equation:

(alpha - beta L) phi = f

where L is the Laplacian and alpha and beta are constants.  If alpha =
0 and beta = -1, then this is the Poisson equation.

We support homogeneous Dirichlet or Neumann BCs, or on periodic domain.

The general usage is as follows:

> a = multigrid.ccMG2d(nx, ny, verbose=1, alpha=alpha, beta=beta)

this creates the multigrid object a, with a finest grid of nx by ny
zones and the default boundary condition types.  alpha and beta are
the coefficients of the Helmholtz equation.  Setting verbose = 1
causing debugging information to be output, so you can see the
residual errors in each of the V-cycles.

> a.initSolution(zeros((nx, ny), numpy.float64))

this initializes the solution vector with zeros

> a.initRHS(zeros((nx, ny), numpy.float64))

this initializes the RHS on the finest grid to 0 (Laplace's equation).
Any RHS can be set by passing through an array of nx values here.

Then to solve, you just do:

> a.solve(rtol = 1.e-10)

where rtol is the desired tolerance (relative difference in solution from
one cycle to the next).

to access the final solution, use the getSolution method

v = a.getSolution()

For convenience, the grid information on the solution level is available as
attributes to the class,

a.ilo, a.ihi, a.jlo, a.jhi are the indices bounding the interior
of the solution array (i.e. excluding the guardcells).

a.x and a.y are the coordinate arrays
a.dx and a.dy are the grid spacings

"""

import mesh.patch as patch
import math
import numpy


def error(myg, r):

    # L2 norm of elements in r, multiplied by dx*dy to
    # normalize
    return numpy.sqrt(myg.dx*myg.dy*
                      numpy.sum((r[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1]**2).flat))
    #return max(r[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1].flat)

class ccMG2d:
    """ 
    The main multigrid class for cell-centered data.

    We require that nx = ny be a power of 2 and dx = dy, for
    simplicity
    """
    
    def __init__(self, nx, ny, xmin=0.0, xmax=1.0, ymin=0.0, ymax=1.0,
                 xlBCtype="dirichlet", xrBCtype="dirichlet",
                 ylBCtype="dirichlet", yrBCtype="dirichlet",
                 alpha=0.0, beta=-1.0,
                 verbose=0):

        if (nx != ny):
            print "ERROR: multigrid currently requires nx = ny"
            return -1
        
        self.nx = nx
        self.ny = ny        
        
        self.ng = 1

        self.xmin = xmin
        self.xmax = xmax

        self.ymin = ymin
        self.ymax = ymax        

        if ((xmax-xmin) != (ymax-ymin)):
            print "ERROR: multigrid currently requires a square domain"
            return -1
        
        self.alpha = alpha
        self.beta = beta

        self.nsmooth = 10

        self.maxCycles = 100
        
        self.verbose = verbose

        # a small number used in computing the error, so we don't divide by 0
        self.small = 1.e-16
        
        # keep track of whether we've initialized the solution
        self.initializedSolution = 0
        self.initializedRHS = 0
        
        # assume that self.nx = 2^nlevels and that nx = ny
        # this defines nlevels such that we end exactly on a 1x1 grid
        self.nlevels = int(math.log(self.nx)/math.log(2.0)) + 1

        # a multigrid object will be a list of grids
        self.grids = []

        # create the grids.  Here, self.grids[0] will be the coarsest
        # grid and self.grids[nlevel-1] will be the finest grid
        # we store the solution, v, the rhs, f.
        i = 0
        nx_t = ny_t = 1

        if (self.verbose):
            print "alpha = ", self.alpha
            print "beta  = ", self.beta

        while (i < self.nlevels):
            
            # create the grid
            myGrid = patch.grid2d(nx_t, ny_t, ng=self.ng,
                                  xmin=xmin, xmax=xmax,
                                  ymin=ymin, ymax=ymax)

            # add a ccData2d object for this level to our list
            self.grids.append(patch.ccData2d(myGrid, dtype=numpy.float64))

            # create the boundary condition object
            bcObj = patch.bcObject(xlb=xlBCtype, xrb=xrBCtype,
                                   ylb=ylBCtype, yrb=yrBCtype)

            self.grids[i].registerVar("v", bcObj)
            self.grids[i].registerVar("f", bcObj)
            self.grids[i].registerVar("r", bcObj)

            self.grids[i].create()

            if self.verbose:
                print self.grids[i]        

            nx_t = nx_t*2
            ny_t = ny_t*2

            i += 1


        # provide coordinate and indexing information for the solution mesh
        solnGrid = self.grids[self.nlevels-1].grid

        self.ilo = solnGrid.ilo
        self.ihi = solnGrid.ihi
        self.jlo = solnGrid.jlo
        self.jhi = solnGrid.jhi
        
        self.x  = solnGrid.x
        self.dx = solnGrid.dx

        self.x2d = solnGrid.x2d

        self.y  = solnGrid.y
        self.dy = solnGrid.dy   # note, dy = dx is assumed 

        self.y2d = solnGrid.y2d

        self.solnGrid = solnGrid

        # store the source norm
        self.sourceNorm = 0.0

        # after solving, keep track of the number of cycles taken, the
        # relative error from the previous cycle, and the residual error
        # (normalized to the source norm)
        self.numCycles = 0
        self.residualError = 1.e33
        self.relativeError = 1.e33

    
    def getSolution(self):
        v = self.grids[self.nlevels-1].getVarPtr("v")
        return v.copy()
        

    def getSolutionObjPtr(self):
        myData = self.grids[self.nlevels-1]
        return myData


    def initSolution(self, data):
        """
        initialize the solution to the elliptic problem by passing in
        a value for all defined zones
        """
        v = self.grids[self.nlevels-1].getVarPtr("v")
        v[:,:] = data.copy()

        self.initializedSolution = 1


    def initZeros(self):
        """
        set the initial solution to zero
        """
        v = self.grids[self.nlevels-1].getVarPtr("v")
        v[:,:] = 0.0

        self.initializedSolution = 1


    def initRHS(self, data):
        f = self.grids[self.nlevels-1].getVarPtr("f")
        f[:,:] = data.copy()

        # store the source norm
        self.sourceNorm = error(self.grids[self.nlevels-1].grid, f)

        if (self.verbose):
            print "Source norm = ", self.sourceNorm

        # note: if we wanted to do inhomogeneous Dirichlet BCs, we 
        # would modify the source term, f, here to include a boundary
        # charge

        self.initializedRHS = 1
        

    def computeResidual(self, level):
        """ compute the residual and store it in the r variable"""

        v = self.grids[level].getVarPtr("v")
        f = self.grids[level].getVarPtr("f")
        r = self.grids[level].getVarPtr("r")

        myg = self.grids[level].grid

        # compute the residual 
        # r = f - alpha phi + beta L phi
        r[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1] = \
            f[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1] - \
            self.alpha*v[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1] + \
            self.beta*( 
            (v[myg.ilo-1:myg.ihi  ,myg.jlo  :myg.jhi+1] + 
             v[myg.ilo+1:myg.ihi+2,myg.jlo  :myg.jhi+1] - 
             2.0*v[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1])/(myg.dx*myg.dx) + 
            (v[myg.ilo  :myg.ihi+1,myg.jlo-1:myg.jhi  ] +
             v[myg.ilo  :myg.ihi+1,myg.jlo+1:myg.jhi+2] -
             2.0*v[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1])/(myg.dy*myg.dy) )

        print "in residual"
        print numpy.min(r), numpy.min(f)
        print numpy.max(r), numpy.max(f)
        
        
        
    def smooth(self, level, nsmooth):
        """ use Gauss-Seidel iterations to smooth """
        v = self.grids[level].getVarPtr("v")
        f = self.grids[level].getVarPtr("f")

        myg = self.grids[level].grid

        self.grids[level].fillBC("v")

        # do red-black G-S
        i = 0
        while (i < nsmooth):

            print "min/max", numpy.min(v), numpy.max(v)

            xcoeff = self.beta/myg.dx**2
            ycoeff = self.beta/myg.dy**2

            # do the red black updating in four decoupled groups
            v[myg.ilo:myg.ihi+1:2,myg.jlo:myg.jhi+1:2] = \
                (f[myg.ilo:myg.ihi+1:2,myg.jlo:myg.jhi+1:2] +
                 xcoeff*(v[myg.ilo+1:myg.ihi+2:2,myg.jlo  :myg.jhi+1:2] +
                         v[myg.ilo-1:myg.ihi  :2,myg.jlo  :myg.jhi+1:2]) +
                 ycoeff*(v[myg.ilo  :myg.ihi+1:2,myg.jlo+1:myg.jhi+2:2] +
                         v[myg.ilo  :myg.ihi+1:2,myg.jlo-1:myg.jhi  :2])) / \
                (self.alpha + 2.0*xcoeff + 2.0*ycoeff)

            v[myg.ilo+1:myg.ihi+1:2,myg.jlo+1:myg.jhi+1:2] = \
                (f[myg.ilo+1:myg.ihi+1:2,myg.jlo+1:myg.jhi+1:2] +
                 xcoeff*(v[myg.ilo+2:myg.ihi+2:2,myg.jlo+1:myg.jhi+1:2] +
                         v[myg.ilo  :myg.ihi  :2,myg.jlo+1:myg.jhi+1:2]) +
                 ycoeff*(v[myg.ilo+1:myg.ihi+1:2,myg.jlo+2:myg.jhi+2:2] +
                         v[myg.ilo+1:myg.ihi+1:2,myg.jlo  :myg.jhi  :2])) / \
                (self.alpha + 2.0*xcoeff + 2.0*ycoeff)
            
            self.grids[level].fillBC("v")
                                                     
            v[myg.ilo+1:myg.ihi+1:2,myg.jlo:myg.jhi+1:2] = \
                (f[myg.ilo+1:myg.ihi+1:2,myg.jlo:myg.jhi+1:2] +
                 xcoeff*(v[myg.ilo+2:myg.ihi+2:2,myg.jlo  :myg.jhi+1:2] +
                         v[myg.ilo  :myg.ihi  :2,myg.jlo  :myg.jhi+1:2]) +
                 ycoeff*(v[myg.ilo+1:myg.ihi+1:2,myg.jlo+1:myg.jhi+2:2] +
                         v[myg.ilo+1:myg.ihi+1:2,myg.jlo-1:myg.jhi  :2])) / \
                (self.alpha + 2.0*xcoeff + 2.0*ycoeff)

            v[myg.ilo:myg.ihi+1:2,myg.jlo+1:myg.jhi+1:2] = \
                (f[myg.ilo:myg.ihi+1:2,myg.jlo+1:myg.jhi+1:2] +
                 xcoeff*(v[myg.ilo+1:myg.ihi+2:2,myg.jlo+1:myg.jhi+1:2] +
                         v[myg.ilo-1:myg.ihi  :2,myg.jlo+1:myg.jhi+1:2]) +
                 ycoeff*(v[myg.ilo  :myg.ihi+1:2,myg.jlo+2:myg.jhi+2:2] +
                         v[myg.ilo  :myg.ihi+1:2,myg.jlo  :myg.jhi  :2])) / \
                (self.alpha + 2.0*xcoeff + 2.0*ycoeff)


            self.grids[level].fillBC("v")
                                                     
            i += 1



    def solve(self, rtol = 1.e-11):

        # start by making sure that we've initialized the solution
        # and the RHS
        if (not self.initializedSolution or not self.initializedRHS):
            msg.fail("ERROR: solution and RHS are not initialized")

        # for now, we will just do V-cycles, continuing until we
        # achieve the L2 norm of the relative solution difference is <
        # rtol
        if self.verbose:
            print "source norm = ", self.sourceNorm
            
        oldSolution = self.grids[self.nlevels-1].getVarPtr("v").copy()
        
        converged = 0
        cycle = 1

        while (not converged and cycle <= self.maxCycles):

            # zero out the solution on all but the finest grid
            level = 0
            while (level < self.nlevels-1):
                v = self.grids[level].zero("v")
                level += 1            

            # descending part
            if self.verbose:
                print "<<< beginning V-cycle (cycle %d) >>>\n" % cycle

            level = self.nlevels-1
            while (level > 0):

                fP = self.grids[level]
                cP = self.grids[level-1]

                # access to the residual
                r = fP.getVarPtr("r")

                if self.verbose:
                    self.computeResidual(level)

                    print "  level = %d, nx = %d, ny = %d" %  \
                        (level, fP.grid.nx, fP.grid.ny)

                    print "  before G-S, residual L2 norm = %g" % \
                          (error(fP.grid, r) )
            
                # smooth on the current level
                self.smooth(level, self.nsmooth)

            
                # compute the residual
                self.computeResidual(level)

                if self.verbose:
                    print "  after G-S, residual L2 norm = %g\n" % \
                          (error(fP.grid, r) )


                # restrict the residual down to the RHS of the coarser level
                f_coarse = cP.getVarPtr("f")
                f_coarse[:,:] = fP.restrict("r")

                level -= 1


            # solve the discrete coarse problem exactly
            if self.verbose:
                print "  <<< bottom solve >>>\n"

            bP = self.grids[0]
            v = bP.getVarPtr("v")
            f = bP.getVarPtr("f")        

            v[bP.grid.ilo] = -0.125*f[bP.grid.ilo]*bP.grid.dx*bP.grid.dx

            bP.fillBC("v")

            
            # ascending part
            level = 1
            while (level < self.nlevels):

                fP = self.grids[level]
                cP = self.grids[level-1]

                # prolong the error up from the coarse grid
                e = cP.prolong("v")

                # correct the solution on the current grid
                v = fP.getVarPtr("v")
                v += e

                if self.verbose:
                    self.computeResidual(level)
                    r = fP.getVarPtr("r")

                    print "  level = %d, nx = %d, ny = %d" % \
                        (level, fP.grid.nx, fP.grid.ny)

                    print "  before G-S, residual L2 norm = %g" % \
                          (error(fP.grid, r) )
            
                # smooth
                self.smooth(level, self.nsmooth)

                if self.verbose:
                    self.computeResidual(level)

                    print "  after G-S, residual L2 norm = %g\n" % \
                          (error(fP.grid, r) )
            
                level += 1

            # compute the error with respect to the previous solution
            # this is for diagnostic purposes only -- it is not used to
            # determine convergence
            solnP = self.grids[self.nlevels-1]

            diff = (solnP.getVarPtr("v") - oldSolution)/ \
                (solnP.getVarPtr("v") + self.small)

            relativeError = error(solnP.grid, diff)

            oldSolution = solnP.getVarPtr("v").copy()

            # compute the residual error, relative to the source norm
            self.computeResidual(self.nlevels-1)
            r = fP.getVarPtr("r")

            if (self.sourceNorm != 0.0):
                residualError = error(fP.grid, r)/self.sourceNorm
            else:
                residualError = error(fP.grid, r)

                
            if (residualError < rtol):
                converged = 1
                self.numCycles = cycle
                self.relativeError = relativeError
                self.residualError = residualError
                fP.fillBC("v")
                
            if self.verbose:
                print "cycle %d: relative err = %g, residual err = %g\n" % \
                      (cycle, relativeError, residualError)
            
            cycle += 1



        
        
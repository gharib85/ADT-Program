import os
import sys
import shutil
import textwrap
import subprocess
import numpy as np
import ConfigParser

import math

angtobohr = 1.8897259886
hbar = 0.063508
cInvToTauInv = 0.001883651

scrdir = '/tmp/adtprogram'



#*create template functions will most probably be same 
# *in both spec and scatter case


def dotp(x,y):
    """ dot product of two pairs """
    return x[0]*y[0] + x[1]*y[1]

def AreaTriangle(a,b,c):
    """ area of a tringle with sides a,b,c """
    ps = (a+b+c)/2.0
    ar = ps*(ps-a)*(ps-b)*(ps-c)
    # negative area due to round off errors set to zero
    if ar < 0.0:
        ar = 0.0
    ar = math.sqrt(ar)
    return ar



def to_jacobi(self,theta,phi):

    """ returns jacobi coordinates """
    #!are theta phi taken in degree or radian
    #! depending on that numpy cos/sin will be replaced by the ones defined in the class
    m1, m2, m3 = self.atomMass

    M = m1 + m2 + m3
    mu = np.sqrt(m1*m2*m3/M)
    d1 = np.sqrt(m1*(m2+m3)/(mu*M))
    d2 = np.sqrt(m2*(m3+m1)/(mu*M))
    d3 = np.sqrt(m3*(m1+m2)/(mu*M))
    eps3 = 2 * np.atan(m2/mu)
    eps2 = 2 * np.atan(m3/mu)

    R1 = (1.0/np.sqrt(2.0))*self.rho*d3*np.sqrt(1.0+np.sin(theta)*np.cos(phi+eps3)) # F-H2 distance
    R2 = (1.0/np.sqrt(2.0))*self.rho*d1*np.sqrt(1.0+np.sin(theta)*np.cos(phi))      # H1-H2 distance
    R3 = (1.0/np.sqrt(2.0))*self.rho*d2*np.sqrt(1.0+np.sin(theta)*np.cos(phi-eps2)) # F-H1 distance

    if R1 < 1e-10:
       R1 = 0.0
    if R2 < 1e-10:
       R2 = 0.0
    if R3 < 1e-10:
       R3 = 0.0

    area = AreaTriangle(R1,R2,R3)
    x = R2*R2 + R3*R3 - R1*R1
    y = 4.0*area
    Ang123 = np.atan2(y,x)
    x2 = (0.0,0.0)
    x3 = (R2,0.0)
    x1 = (R3*np.cos(Ang123),R3*np.sin(Ang123))
    # these are non-mass scaled jacobi coords
    # r : (x3-x2)
    # R : x1 - com(x3,x2)
    # gamma : angle between r and R
    r = (R2,0.0)
    R = (R3*np.cos(Ang123) - m3*R2/(m2+m3) , R3*np.sin(Ang123))
    rs = np.sqrt(dotp(r,r))
    rc = np.sqrt(dotp(R,R))
    if rc < 1e-10:
       rc = 0.0

    rtil = (R2*m2/(m2+m3),0.0)
    drtil = np.sqrt(dotp(rtil,rtil))
    Areasmall = AreaTriangle(drtil,R1,rc)
    y = 4.0 * Areasmall
    x = drtil*drtil + rc*rc - R1*R1
    if np.fabs(x) < 1e-10:
       x = 0.0
    gamma = np.atan2(y,x)

    # we assert that gamma is always less than 90 degree always - our grid does not produce this for H2F
    # assert (gamma <= np.pi/2)

    return (rs, rc, gamma)



def hyperToCart(self, theta, phi):
    rs, rc, gamma = to_jacobi(theta, phi)
    #! this gamma is in radian, so numpy sin cos can be used.
    p1 = [0, rc*math.cos(gamma),rc*math.sin(gamma)]
    p2 = [0, -rs/2.0 , 0.0 ]
    p3 = [0, rs/2.0  , 0.0 ]
    return np.array([p1,p2,p3])


# def jacobixyz(rs,rc,gamm):  # rs is jacobi 'r', rc is jacobi 'R' gamm is jacobi 'gamma'
#     # xyz coordinates generated from jacobi coordinates
#     # use global variables m1,m2,m3 to assign the masses of the atoms
#     p1 = m1,(rc*math.cos(gamm),rc*math.sin(gamm))
#     p2 = m2,( -rs/2.0 , 0.0 )
#     p3 = m3,( rs/2.0 , 0.0 )
#     return p1,p2,p3





class ScatterFuncs():
    """
        documentation
    """
    #provide atom mass and names in atomFile.dat
    def __init__(self, 
            conFigFile= 'molpro.config',
            atomFile  = 'atomFile.dat'):

        #parse configuration for running molpro
        scf = ConfigParser.SafeConfigParser()
        scf.read(conFigFile)
        self.eInfo = dict(scf.items('eInfo'))
        self.nInfo = dict(scf.items('nInfo'))


        gInfo = dict(scf.items('gInfo'))
        gInfo['firstgrid'] = map(float, gInfo['firstgrid'].split(','))
        gInfo['secondgrid'] = map(float, gInfo['secondgrid'].split(','))

        self.state = int(self.eInfo['state'])
        self.nactPairs = [[i,j] for i in range(1,self.state+1) for j in range(i+1,self.state+1)]
        self.dt = gInfo['firstgrid'][2]/100              #setting the dr dp as 1/100 times the stepsize
        self.dp = gInfo['secondgrid'][2]/100

        #Include the end points ..............?
        self.theta_grid = np.arange(*gInfo['firstgrid'])
        self.phi_grid = np.arange(*gInfo['secondgrid'])


        #read atom names and masses from the atom file
        #move this to the parse data function
        atomData = np.loadtxt(atomFile, 
            dtype={'names': ('names', 'mass'),'formats': ('S1', 'f8')})

        self.atomNames = atomData['names']
        self.atomMass  = atomData['mass']


        #crete template file appropriate for method
        if self.nInfo['method']=='cpmcscf':
            self.createAnaTemplate()
            self.getTauThetaPhi = self.getTauThetaPhiAna

        elif self.nInfo['method']=='ddr':
            self.dr = gInfo['df']
            self.dp = gInfo['ds']
            self.createDDRTemplate()
            self.createGridGeom = self.createDdrGridGeom
            self.getTauThetaPhi = self.getTauThetaPhiDdr

        else:
            sys.exit('%s Not a proper option'%self.nInfo['method'])
    
        #Run molpro here
        #?Is it good to put this inside the constructor ??????
        self.runMolpro()


    def sin(self, x):
        """ A sin function that directly takes degree as input unlike numpy"""
        return np.sin(np.deg2rad(x))


    def cos(self, x):
        """ A cos function that directly takes degree as input unlike numpy"""
        return np.cos(np.deg2rad(x))


    #* both the template funtions will be moved to the global scope
    #* so all the edits are being made only to the ones on spectroscopic class
    def createAnaTemplate(self):
        molproEquiTemplate=textwrap.dedent('''
            ***, Molpro template created from ADT program for "WhatEver"
            file,2,molpro.wfu,new;

            basis=6-31G**;

            symmetry,nosym

            geometry=geom.xyz

            {{uhf;orbital,2200.2}}
            {{{method};{cas}; wf,{wf};state,{state};orbital,2140.2;}}

            show, energy
            table, energy
            save,equienr.res,new
            {{table,____; noprint,heading}}

            ---

            '''.format(memory = self.memory,
                        method=self.eInfo['method'],
                        state=self.eInfo['state'],
                        wf =  self.eInfo['wf'],
                        cas = self.eInfo['cas']))

        with open('equi.com' ,'w') as f:
            f.write(molproEquiTemplate)



        molproGridTemplate=textwrap.dedent('''
            ***, Molpro template created from ADT program for "WhatEver"
            memory,100,m
            file,2,molpro.wfu;

            basis=6-31G**;

            symmetry,nosym


            geometry=geom.xyz

            {{{method};{cas}; wf,{wf};state,{state};start,2140.2; orbital,2140.2;}}

            show, energy
            table, energy
            save,enr.res,new
            {{table,____; noprint,heading}}
            '''.format(method=self.eInfo['method'],
                        state=self.eInfo['state'],
                        wf =  self.eInfo['wf'],
                        cas = self.eInfo['cas']))


        nactTemp= "\n\nbasis={}\n".format(self.eInfo['basis'])

        for ind in range(0,len(self.nactPairs),5):
            nactTemp += "\n{{{method};{cas}; wf,{wf};state,{state}; start,2140.2;\n".format(
                                method=self.eInfo['method'],
                                state=self.eInfo['state'],
                                wf =  self.eInfo['wf'],
                                cas = self.eInfo['cas'])

            pairChunk = self.nactPairs[ind:ind+5]
            forceTemp = ''
            for i,j in pairChunk:
                nactTemp += "{nmethod},nacm,{f}.1,{s}.1,record=51{f}{s}.1;\n".format(
                            nmethod = self.nInfo['method'],
                            f=i,s=j)
                forceTemp +=textwrap.dedent("""
                force;nacm,51{f}{s}.1;varsav
                table,gradx,grady,gradz;
                save,ananac{f}{s}.res,new;
                {{table,____;  noprint,heading}}

                """.format(f=i,s=j))
            nactTemp += "}\n" + forceTemp




        molproGridTemplate += nactTemp + '\n---\n'

        with open('grid.com','w') as f:
            f.write(molproGridTemplate)


    def createDDRTemplate(self):
        molproEquiTemplate=textwrap.dedent('''
            ***, Molpro template created from ADT program for "WhatEver"
            memory,500,m
            file,2,molpro.wfu,new;

            basis=6-31G**;

            symmetry,nosym


            geometry=geom.xyz

            {{uhf;orbital,2200.2}}
            {{multi;occ,{occ};closed,{closed}; wf,{wf};state,{state};orbital,2140.2;}}
            {{mrci; occ,{occ};closed,{closed};core,{core}; wf,{wf};state,{state};save,6000.2;noexc}}
            show,  energy
            table, energy
            save,equienr.res,new
            {{table,____; noprint,heading}}

            ---

            '''.format( state=self.eInfo['state'],
                        wf =  self.eInfo['wf'],
                        occ= self.eInfo['occ'],
                        closed = self.eInfo['closed'],
                        core = self.eInfo['core']))

        with open('equi.com' ,'w') as f:
            f.write(molproEquiTemplate)



        molproGridTemplate=textwrap.dedent('''
            ***, Molpro template created from ADT program for "WhatEver"
            memory,500,m
            file,2,molpro.wfu;

            basis=6-31G**;

            symmetry,nosym

            geomtyp=xyz
            geometry=geom1.xyz

            {{multi;occ,{occ};closed,{closed}; wf,{wf};state,{state};orbital,2140.2;}}
            {{mrci; occ,{occ};closed,{closed};core,{core}; wf,{wf};state,{state};save,6000.2;noexc}}

            show, energy
            table, energy
            save,enr.res,new
            {{table,____; noprint,heading}}

            !for +dr
            symmetry,nosym
            geometry=geom2.xyz
            {{multi;occ,{occ};closed,{closed}; wf,{wf};state,{state};start,2140.2;orbital,2241.2;}}
            {{mrci; occ,{occ};closed,{closed};core,{core}; wf,{wf};state,{state};save,6001.2;noexc}}
            {{ci;trans,6000.2,6001.2;dm,8001.2}}


            !for -dr
            symmetry,nosym
            geometry=geom3.xyz
            {{multi;occ,{occ};closed,{closed}; wf,{wf};state,{state};start,2140.2;orbital,2242.2;}}
            {{mrci; occ,{occ};closed,{closed};core,{core}; wf,{wf};state,{state};save,6002.2;noexc}}
            {{ci;trans,6000.2,6002.2;dm,8002.2}}



            !for +dp
            symmetry,nosym
            geometry=geom4.xyz
            {{multi;occ,{occ};closed,{closed}; wf,{wf};state,{state};start,2140.2;orbital,2243.2;}}
            {{mrci; occ,{occ};closed,{closed};core,{core}; wf,{wf};state,{state};save,6003.2;noexc}}
            {{ci;trans,6000.2,6003.2;dm,8003.2}}


            !for -dp
            symmetry,nosym
            geometry=geom5.xyz
            {{multi;occ,{occ};closed,{closed}; wf,{wf};state,{state};start,2140.2;orbital,2244.2;}}
            {{mrci; occ,{occ};closed,{closed};core,{core}; wf,{wf};state,{state};save,6004.2;noexc}}
            {{ci;trans,6000.2,6004.2;dm,8004.2}}


            '''.format( state=self.eInfo['state'],
                        wf =  self.eInfo['wf'],
                        occ= self.eInfo['occ'],
                        closed = self.eInfo['closed'],
                        core = self.eInfo['core']))


        nactTemp= ''

        for i,j in self.nactPairs:
            nactTemp+=textwrap.dedent(''' 
                !for taur     
                {{ddr,{dr},2140.2,2241.2,8001.2;state, {j}.1,{i}.1}}
                nacmepv=nacme

                {{ddr,-{dr},2140.2,2242.2,8002.2;state, {j}.1,{i}.1}}
                nacmemv=nacme

                nacmr = 0.5*(nacmepv+ nacmemv)

                !for taup
                {{ddr,{dp},2140.2,2243.2,8003.2;state, {j}.1,{i}.1}}
                nacmepv=nacme

                {{ddr,-{dp},2140.2,2244.2,8004.2;state, {j}.1,{i}.1}}
                nacmemv=nacme
                nacmp = 0.5*(nacmepv+ nacmemv)


                table, nacmr,nacmp
                save,ddrnact{i}{j}.res,new;

                
                '''.format(dr=self.dr,dp=self.dp,i=i,j=j))



        molproGridTemplate += nactTemp + '\n---\n'

        with open('grid.com','w') as f:
            f.write(molproGridTemplate)



    def createGridGeom(self, theta, phi, outFile = 'geom.xyz'):
        
        curGeom  = hyperToCart(theta, phi)
        msg = 'for Rho = {}, Theta={}, Phi = {}'.format(self.rho, theta, phi)
        nAtoms = len(self.atomNames)
        tmp = " {}\n".format(nAtoms)
        tmp+= "Geometry file created from ADT program. %s \n"%msg
        for i in range(nAtoms):
            tmp += "{},{},{},{}\n".format(self.atomNames[i], *curGeom[i])

        with open(outFile,"w") as f:
            f.write(tmp)


    def createDdrGridGeom(self, theta, phi):
        createGridGeom(atomNames, theta,    phi,    'geom1.xyz')
        createGridGeom(atomNames, theta+self.dt, phi,   'geom2.xyz')
        createGridGeom(atomNames, theta-self.dt, phi,   'geom3.xyz')
        createGridGeom(atomNames, theta,    phi+self.dp,'geom4.xyz')
        createGridGeom(atomNames, theta,    phi-self.dp,'geom5.xyz')
    

    def parseResult(self, file):
        with open(file,"r") as f:
            dat = f.read().replace("D","E").strip().split("\n")[1:]
        dat = [map(float,i.strip().split()) for i in dat]
        return np.array(dat)


    def parseNact(self, i,j,rho,phi):
        file = 'ananac{}{}.res'.format(i,j)
        grads = angtobohr*parseResult(file)

        tauTheta = np.einsum('ij,ij', grads, grad_theta)
        tauPhi   = np.einsum('ij,ij', grads, grad_phi)
        return np.array([tauTheta, tauPhi])



    def getTauThetaPhiAna(self, theta, phi):
        # What will be this values
        d_theta = 0.001
        d_phi = 0.01

        grad_theta_plus = hyperToCart(theta+d_theta, phi)
        grad_theta_minus = hyperToCart(theta-d_theta, phi)
        grad_theta      = (grad_theta_plus - grad_theta_minus)/2*d_theta

        grad_phi_plus = hyperToCart(theta+d_theta, phi)
        grad_phi_minus = hyperToCart(theta-d_theta, phi)
        grad_phi      = (grad_phi_plus - grad_phi_minus)/2*d_phi 
    
        return np.stack((parseNact(i,j,rho,phi, grad_theta, grad_phi) 
                                    for i,j in self.nactPairs)).T


    def getTauThetaPhiDdr(self, *args):
        return np.stack((self.parseResult('ddrnact{}{}.res'.format(i,j)) 
                                    for i,j in self.nactPairs)).T

    #include the theta =0 , phi = 0 step


    def runMolpro(self):

        #initialise blank arrays to store result
        energyResult  = np.array([], dtype=np.float64).reshape(0,self.state+2) 
        nactRhoResult = np.array([], dtype=np.float64).reshape(0,nTau+2)
        nactPhiResult = np.array([], dtype=np.float64).reshape(0,nTau+2)


        for phi in self.phi_grid[:1]:
            for theta in self.theta_grid[:1]:

                self.createGridGeom(theta, phi) 
                shutil.copy('molpro.wfu',scrdir)

                exitcode = subprocess.call(['molpro',"-d", scrdir,'-W .','grid.com'])
                if exitcode==0:
                    print 'Job successful  '+msg
                else : 
                    print 'Job unsuccessful'+msg 
                    continue


                enrData = parseResult('enr.res').flatten()
                tauTheta, tauPhi = self.getTauThetaPhi(theta, phi)


                energyResult  = np.vstack((energyResult,  np.append([theta, phi],enrData)))
                nactThetaResult = np.vstack((nactThetaResult, np.append([theta, phi],tauTheta)))
                nactPhiResult = np.vstack((nactPhiResult, np.append([theta, phi],tauPhi)))

        self.writeFile('energy.dat', energyResult)
        self.writeFile('tau_theta.dat', nactThetaResult)
        self.writeFile('tau_phi.dat', nactPhiResult)


    def writeFile(self, file, data):
        #along rho or along phi?
        for tp in self.theta_grid:
            np.savetxt( file, data[data[:,fc]==tp] ,delimiter="\t", fmt="%.8f")
            file.write("\n")


# if __name__ == "__main__":
#     ScatterFuncs()
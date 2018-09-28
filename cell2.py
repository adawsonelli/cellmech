#!/usr/bin/python  -u

import collections
import copy
import itertools
import sys
from math import exp, log, sqrt
import warnings
import numpy as np
import numpy.random as npr

warnings.filterwarnings("error")

null = np.array([0.0, 0.0, 0.0])
ex = np.array([1.0, 0.0, 0.0])
ey = np.array([0.0, 1.0, 0.0])
ez = np.array([0.0, 0.0, 1.0])


def ccw(A, B, C):
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])


def getNormvec(v):
    # returns normalized v
    d = np.linalg.norm(v)
    try:
        v = v/d
    except RuntimeWarning:
        pass
    return v


def getNormtoo(v):
    # returns norm of v and normalized v
    d = np.linalg.norm(v)
    try:
        v = v/d
    except RuntimeWarning:
        d = 0
    return v, d


def intersect(A, B, C, D):
    if np.linalg.norm(A - C) < 0.01:
        return False
    if np.linalg.norm(A - D) < 0.01:
        return False
    if np.linalg.norm(B - C) < 0.01:
        return False
    return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)


def getRotMatArray(Phis):
    Thetas = np.linalg.norm(Phis)
    Thetas[np.where(Thetas == 0)] = np.inf
    Axes = Phis / Thetas[..., None]
    a = np.cos(Thetas / 2)
    b, c, d = np.transpose(Axes) * np.sin(Thetas / 2)
    RotMat = np.array([[a * a + b * b - c * c - d * d, 2 * (b * c - a * d), 2 * (b * d + a * c)],
                      [2 * (b * c + a * d), a * a + c * c - b * b - d * d, 2 * (c * d - a * b)],
                      [2 * (b * d - a * c), 2 * (c * d + a * b), a * a + d * d - b * b - c * c]])
    return np.transpose(RotMat, axes=(2, 0, 1))


def getRotMat(Phis):
    Axis, Theta = getNormtoo(Phis)
    a = np.cos(Theta / 2)
    b, c, d = Axis * np.sin(Theta / 2)
    return np.array([[a * a + b * b - c * c - d * d, 2 * (b * c - a * d), 2 * (b * d + a * c)],
                    [2 * (b * c + a * d), a * a + c * c - b * b - d * d, 2 * (c * d - a * b)],
                    [2 * (b * d - a * c), 2 * (c * d + a * b), a * a + d * d - b * b - c * c]])


def update_progress(progress):
    """
    Simple progress bar update.
    :param progress: float. Fraction of the work done, to update bar.
    :return:
    """
    barLength = 20  # Modify this to change the length of the progress bar
    status = ""
    if isinstance(progress, int):
        progress = float(progress)
    if not isinstance(progress, float):
        progress = 0
        status = "error: progress var must be float\r\n"
    if progress < 0:
        progress = 0
        status = "Halt...\r\n"
    if progress >= 1:
        progress = 1
        status = "Done...\r\n"
    block = int(round(barLength * progress))
    text = "\rProgress: [{0}] {1} % {2}".format("#" * block + "-" * (barLength - block), round(progress * 100, 1),
                                                status)
    sys.stdout.write(text)
    sys.stdout.flush()


class Configuration:
    def __init__(self, num, dt=0.01, nmax=3000, qmin=0.001, d0_0=1, force_limit=15., p_add=1.,
                 p_del=0.2, chkx=True, anis=0.0, d0max=2., unrestricted=True, distlimit=3):
        # parameters for mechanical equilibration
        self.dt = dt
        self.nmax = nmax
        self.qmin = qmin
        # parameters to add/remove links
        self.d0_0 = d0_0
        self.force_limit = force_limit
        self.p_add = p_add
        self.p_del = p_del
        self.chkx = chkx
        self.anis = anis
        self.d0max = d0max
        # parameters to restrict mech. equilibration to surrounding of changed link
        self.unrestricted = unrestricted
        self.distlimit = distlimit
        # variables to store cell number and cell positions and angles
        self.N = num
        self.ones = np.ones(self.N)

        """description of nodes"""
        self.nodes = np.zeros((self.N, 2, 3))           # r and phi of nodes
        self.Fnode = np.zeros((self.N, 3))              # total force on node
        self.Mnode = np.zeros((self.N, 3))              # total torsion on node

        """description of links"""
        # islink[i, j] is True if nodes i and j are connected via link
        self.islink = np.full((self.N, self.N), False)  # Describes link at node [0] leading to node [1]

        self.e = np.zeros((self.N, self.N, 3))          # direction connecting nodes (a.k.a. "actual direction")
        self.d = np.zeros((self.N, self.N))             # distance between nodes (a.k.a. "actual distance")
        self.k = np.zeros((self.N, self.N))             # spring constant between nodes
        self.bend = 10. * np.ones(self.N, self.N)       # bending rigidity
        self.twist = 1. * np.ones(self.N, self.N)       # torsion spring constant
        self.d0 = np.zeros((self.N, self.N))            # equilibrium distance between nodes,
        self.t = np.zeros((self.N, self.N, 3))          # tangent vector of link at node (a.k.a. "preferred direction")
        self.norm = np.zeros((self.N, self.N, 3))       # normal vector of link at node
        self.Mlink = np.zeros((self.N, self.N, 3))      # Torsion from link on node
        self.Flink = np.zeros((self.N, self.N, 3))      # Force from link on node

    def addlink(self, n1, n2, t1=None, t2=None, d0=None, k=None, bend=None, twist=None, n=None, norm1=None, norm2=None):
        ni = n1
        mi = n2

        self.islink[ni, mi], self.islink[mi, ni] = True, True

        if k is None:
            k = 15.
        self.k[ni, mi], self.k[mi, ni] = k, k  # spring parameter
        if bend is not None:
            self.bend[mi, ni], self.bend[ni, mi] = bend, bend
        if twist is not None:
            self.twist[mi, ni], self.bend[ni, mi] = twist, twist

        if d0 is None:
            d0 = self.d[ni, mi]
        self.d0[ni, mi], self.d0[mi, ni] = d0, d0  # equilibrium distance
        # preferred directions
        RotMat1 = getRotMat(-self.nodes[ni, 1])
        RotMat2 = getRotMat(-self.nodes[mi, 1])
        if t1 is None:
            self.t[ni, mi] = np.dot(RotMat1, self.e[ni, mi])
        else:
            self.t[ni, mi] = getNormvec(t1)
        if t2 is None:
            self.t[mi, ni] = np.dot(RotMat2, self.e[mi, ni])
        else:
            self.t[mi, ni] = getNormvec(t2)
        if n is None:
            n, q = getNormtoo(np.cross(self.e[ni, mi], ez))  # n is perpendicular to e
            # n is perpendicular to z (l is in the x-y plane)
            if q < 1e-5:
                n = getNormvec(np.cross(self.e[ni, mi], ex))  # e || ez   =>	n is perpendicular to x
        if norm1 is None:
            norm1 = np.dot(RotMat1, n)
        self.norm[ni, mi] = norm1
        if norm2 is None:
            norm2 = np.dot(RotMat2, n)
        self.norm[mi, ni] = norm2

    def removelink(self, n1, n2):
        ni = n1
        mi = n2

        self.islink[ni, mi], self.islink[mi, ni] = False, False
        self.Flink[ni, mi], self.Flink[mi, ni], self.Mlink[ni, mi], self.Mlink[mi, ni] = null, null, null, null

    def updateDists(self, X):
        dX = X - np.tile(np.expand_dims(X, 1), (1, X.shape[0], 1))
        self.d = np.linalg.norm(dX, axis=2)
        inds = np.where(self.d == 0)
        self.d[inds] = np.infty
        self.e = dX / self.d[..., None]

    def compactStuffINeed(self):
        # get only those parts of the big arrays that are actually needed
        t = self.norm[self.islink]
        norm = self.norm[self.islink]
        normT = norm.transpose(norm, axes=(1, 0, 2))
        bend = self.bend[self.islink]
        twist = self.twist[self.islink]
        k = self.k[self.islink]
        d0 = self.d0[self.islink]
        nodeinds = np.where(self.islink is True)

        return t, norm, normT, bend, twist, k, d0, nodeinds

    def updateLinkForces(self, X, T, Norm, NormT, Bend, Twist, K, D0, Nodeinds):
        Nodes = X[Nodeinds[0]]
        NodesT = X[Nodeinds[1]]
        E = self.e[self.islink]
        D = self.d[self.islink]
        RotMat = getRotMatArray(Nodes[:, 1, :])
        RotMatT = getRotMatArray(NodesT[:, 1, :])

        NormRot = np.einsum("ijk, ik -> ij", RotMat, Norm)

        Norm2 = np.cross(NormRot, E)

        self.Mlink[self.islink] = Bend * np.cross(np.einsum("ijk, ik -> ij", RotMat, T), E) + \
            Twist * np.cross(NormRot, np.einsum("ijk, ik -> ij", RotMatT, NormT))  # Eqs. 5, 6

        M = self.Mlink + np.transpose(self.Mlink, axes=(1, 0, 2))

        self.Flink[self.islink] = np.dot(M[self.islink], Norm2 - Norm) / D[:, None] + \
            K * (D - D0)   # Eqs. 13, 14, 15

    def getForces(self, t, X, norm, normT, bend, twist, k, d0, nodeinds):
        self.updateDists(X)
        self.updateLinkForces(X, t, norm, normT, bend, twist, k, d0, nodeinds)
        self.Fnode = np.sum(self.Flink, axis=1)
        self.Mnode = np.sum(self.Flink, axis=1)

        return np.transpose(np.array([self.Fnode, self.Mnode]), axes=(1, 0, 2))

    def mechEquilibrium(self):
        x = self.nodes.copy()
        h = self.dt
        steps = self.nmax
        t, norm, normT, bend, twist, k, d0, nodeinds = self.compactStuffINeed()
        for i in range(self.nmax):
            k1 = self.getForces(x, t, norm, normT, bend, twist, k, d0, nodeinds)
            Q = np.dot(k1, k1) / len(self.nodes)
            # print i, Q, max([x[n.r][0] for n in self.nodes])
            if Q < self.qmin:
                steps = i + 1
                break
            k1 *= h
            k2 = h * self.getForces(x + k1 / 2, t, norm, normT, bend, twist, k, d0, nodeinds)
            k3 = h * self.getForces(x + k2 / 2, t, norm, normT, bend, twist, k, d0, nodeinds)
            k4 = h * self.getForces(x + k3, t, norm, normT, bend, twist, k, d0, nodeinds)
            x += (k1 + 2 * k2 + 2 * k3 + k4) / 6.
        self.nodes = x
        return steps * h

    def getLinkList(self):
        allLinks0, allLinks1 = np.where(self.islink is True)
        return np.array([[allLinks0[i], allLinks1[i]] for i in range(len(allLinks0)) if allLinks0[i] > allLinks1[i]])

    def checkLinkX(self):
        Xs = []
        delete_list = []
        Links = self.getLinkList()
        for l1, l2 in itertools.combinations(Links, 2):
            if intersect(self.nodes[l1[0], 0], self.nodes[l1[1], 0], self.nodes[l2[0], 0], self.nodes[l2[1], 0]):
                Xs.append([l1, l2])
        while len(Xs) > 0:
            # Counter: count occurence
            # from_iterable: unpack list of lists
            counts = collections.Counter(itertools.chain.from_iterable(Xs))
            # get item most in conflict (highest occurence in list)
            badlink = max(counts, key=counts.get)
            delete_list.append(badlink)
            newXs = [x for x in Xs if badlink not in x]
            Xs = newXs
        for badlink in delete_list:
            self.removelink(badlink[0], badlink[1])

    def delLinkList(self, linklist):
        to_del = []
        for link in linklist:
            if self.d[link[0], link[1]] < self.d0[link[0], link[1]]:
                continue            # compressed links are stable
            f = np.linalg.norm(self.Flink[link[0], link[1]])
            p = exp(f / self.force_limit)
            to_del.append((link, p))
        return to_del

    def tryLink(self, n1, n2, Links):
        if self.islink[n1, n2] is True:
            return -1, null
        for l in Links:
            if intersect(self.nodes[n1, 0], self.nodes[n2, 0], self.nodes[l[0], 0], self.nodes[l[1], 0]):
                return -1, null  # false
        e, d = getNormtoo(self.nodes[n1, 0] - self.nodes[n2, 0])
        if d > self.d0max:
            return -1, null  # false
        return d, e  # true: d>0

    def addLinkList(self, Links):
        to_add = []
        linkcands = np.transpose(np.where(self.d < self.d0max))
        for link in linkcands:
            d, e = self.tryLink(link[0], link[1], Links)
            if d > 1e-5:
                p = (1 - (d / 2.0))
                to_add.append(((link[0], link[1]), p))
        return to_add

    def pickEvent(self, to_del, to_add):
        s1 = 0.
        for (l, p) in to_del:
            s1 += p * self.p_del
        s2 = 0.
        for (q, p) in to_add:
            s2 += p * self.p_add

        S = s1 + s2
        if S < 1e-7:
            print "nothing to do!"
            return 1.
        dt = -log(npr.random()) / S
        if dt > 1:
            print 'Must adjust d0 variables before the next event!'
            return 1.

        r = S * npr.random()
        if r < s1:  # we will remove a link
            for (l, p) in to_del:
                r = r - p * self.p_del
                if r < 0:
                    self.removelink(l[0], l[1])
                    return dt
        r = r - s1
        if r < s2:  # we will add a link
            for ((n1, n2), p) in to_add:
                r = r - p * self.p_add
                if r < 0:
                    self.addlink(n1, n2)
                    return dt

    def default_update_d0(self, dt):
        self.d0 += 0.2 * (self.d0_0 - self.d0) * dt + 0.05 * (
                   2 * sqrt(dt) * npr.random() - sqrt(dt))              # magic number 0.2 and 0.05??

    def modlink(self):
        if self.chkx:
            self.checkLinkX()
        Links = self.getLinkList()
        to_del = self.delLinkList(Links)
        to_add = self.addLinkList(Links)
        dt = self.pickEvent(to_del, to_add)
        self.default_update_d0(dt)
        return dt

    def timeevo(self, tmax, record=False):
        configs, ts = [copy.deepcopy(self)], [0.]
        t = 0.
        while t < tmax:
            dt = self.mechEquilibrium()
            t += dt
            if record:
                configs.append(copy.deepcopy(self))
                ts.append(t)
            dt = self.modlink()
            update_progress(t / tmax)
            t += dt
            if record:
                configs.append(copy.deepcopy(self))
                ts.append(t)
            update_progress(t / tmax)
        if record:
            return configs, ts

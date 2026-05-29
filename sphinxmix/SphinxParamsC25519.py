#!/usr/bin/env python

# Copyright 2011 Ian Goldberg
# Copyright 2016 George Danezis (UCL InfoSec Group)
#
# This file is part of Sphinx.
# 
# Sphinx is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
# 
# Sphinx is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with Sphinx.  If not, see
# <http://www.gnu.org/licenses/>.
#
# The LIONESS implementation and the xcounter CTR mode class are adapted
# from "Experimental implementation of the sphinx cryptographic mix
# packet format by George Danezis".


from os import urandom
from hashlib import sha256
import hmac

from petlib.ec import EcGroup, EcPt, POINT_CONVERSION_UNCOMPRESSED
from petlib.bn import Bn
from petlib.cipher import Cipher

# Python 2/3 compatibility
from builtins import bytes

from nacl.bindings import crypto_scalarmult_base, crypto_scalarmult

def _expand32(K):
    return (K+b"\x00"*32)[:32]

class Group_C25519:
    """Group operations using Curve 25519.

    Security relies on the GDH assumption (Scherer et al., 2023).
    Curve25519 has cofactor 8; DH with low-order points yields all-zeros.
    """

    def __init__(self):
        pass

    def gensecret(self):
        return urandom(32)

    def expon(self, base, exp):
        for f in exp:
            base = crypto_scalarmult(_expand32(f), base)
        return base

    def expon_base(self, exp):
        assert len(exp) > 0
        base = crypto_scalarmult_base(_expand32(exp[0]))
        for f in exp[1:]:
            base = crypto_scalarmult(_expand32(f), base)
        return base

    def makeexp(self, data):
        return data[:32]

    def in_group(self, alpha):
        if len(alpha) != 32:
            return False
        if alpha == b'\x00' * 32:
            return False
        return True

    def validate_shared_secret(self, s):
        """Reject degenerate DH outputs. On Curve25519, small-subgroup inputs yield all-zeros."""
        if len(s) != 32:
            return False
        if s == b'\x00' * 32:
            return False
        return True

    def ddh_verify(self, A, B, C, secret):
        """DDH oracle for Curve25519 (see Group_ECC.ddh_verify)."""
        return C == self.expon(B, [secret])

    def from_bytes(self, data):
        """On Curve25519, points are already 32-byte strings."""
        return data

    def printable(self, alpha):
        return alpha

def test_commut():
    G = Group_C25519()
    x0, x1, x2 = [G.gensecret() for _ in range(3) ]
    x2 = x2[:16]

    assert G.expon_base([x0, x1, x2]) == G.expon_base([x2, x1, x0])

    assert G.expon_base([x0, x1, x2]) == G.expon( G.expon_base([x0, x1]), [ x2 ])
    assert G.expon_base([x0, x2]) == G.expon( G.expon_base([x0]), [ x2 ])

def test_gdh_c25519():
    G = Group_C25519()
    x = G.gensecret()
    y = crypto_scalarmult_base(x)

    r = G.gensecret()
    alpha = crypto_scalarmult_base(r)
    s = G.expon(alpha, [x])

    assert G.in_group(alpha)
    assert G.in_group(s)
    assert G.validate_shared_secret(s)
    assert G.ddh_verify(y, alpha, s, x)

    assert not G.in_group(b'\x00' * 32)
    assert not G.validate_shared_secret(b'\x00' * 32)
    assert not G.in_group(b'\x00' * 31)

    wrong_x = G.gensecret()
    assert not G.ddh_verify(y, alpha, s, wrong_x)
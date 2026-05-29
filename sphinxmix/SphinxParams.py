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

from petlib.ec import EcGroup, POINT_CONVERSION_UNCOMPRESSED
from petlib.bn import Bn
from petlib.cipher import Cipher

# Python 2/3 compatibility
from builtins import bytes

zero_iv = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

class Group_ECC:
    """Group operations in ECC.

    Security relies on the GDH assumption (Scherer et al., 2023): CDH is hard
    even given a DDH oracle. This is believed to hold for standard EC groups.
    """

    def __init__(self, gid=713):
        self.G = EcGroup(gid)
        self.g = self.G.generator()

    def gensecret(self):
        return self.G.order().random()

    def expon(self, base, exp):
        x = exp[0]
        for f in exp[1:]:
            x = x.mod_mul(f, self.G.order())
        b = base
        return (x * b)

    def expon_base(self, exp):
        x = exp[0]
        for f in exp[1:]:
            x = x.mod_mul(f, self.G.order())
        return (x * self.g)

    def makeexp(self, data):
        return (Bn.from_binary(data) % self.G.order())

    def in_group(self, alpha):
        if not self.G.check_point(alpha):
            return False
        if alpha.is_infinite():
            return False
        return True

    def validate_shared_secret(self, s):
        """Reject degenerate DH outputs (identity element). Required for GDH security."""
        if not self.G.check_point(s):
            return False
        if s.is_infinite():
            return False
        return True

    def ddh_verify(self, A, B, C, secret):
        """DDH oracle: given A, B, C and secret x s.t. A = g^x, verify C = B^x.

        Under the GDH assumption, this oracle is available to the CDH attacker
        in the security reduction for Sphinx's RO-KEM (Theorem 2, Scherer et al.).
        """
        return C == self.expon(B, [secret])

    def from_bytes(self, data):
        """Reconstruct an EcPt from its binary representation."""
        from petlib.ec import EcPt
        return EcPt.from_binary(data, self.G)

    def printable(self, alpha):
        return alpha.export(POINT_CONVERSION_UNCOMPRESSED)


class SphinxParams:

    def __init__(self, group=None, header_len = 192, body_len = 1024, assoc_len=0, k=16, dest_len=16):
        self.aes = Cipher("AES-128-CTR")
        self.cbc = Cipher("AES-128-CBC")

        self.assoc_len = assoc_len
        self.max_len = header_len

        self.zero_pad = b"\x00" * (2 * self.max_len)

        self.m = body_len
        self.k = k
        self.dest_len = dest_len

        self.group = group
        if not group:
            self.group = Group_ECC()


    # The LIONESS PRP
    def aes_ctr(self, k, m, iv = zero_iv):      
        #k = bytes(k)
        #m = bytes(m)  
        c = self.aes.enc(k, iv).update(m)
        return bytes(c)

    def aes_cbc_enc(self, k, m, iv = zero_iv):
        cipher = self.cbc.enc(k, iv)
        c = cipher.update(m)
        return bytes(c)

    def aes_cbc_dec(self, k, m, iv = zero_iv):
        last_ct = m[-16:]
        pad_plain = bytes(a ^ b for a, b in zip(b'\x10' * 16, last_ct))
        ecb = Cipher("AES-128-ECB")
        e = ecb.enc(k, b'')
        pad_ct = (e.update(pad_plain) + e.finalize())[:16]
        cipher = self.cbc.dec(k, iv)
        c = cipher.update(m + pad_ct) + cipher.finalize()
        return bytes(c[:len(m)])

    def lioness_enc(self, key, message):
        assert len(key) == self.k
        assert len(message) >= self.k * 2

        # Round 1
        k1 = self.hash(message[self.k:]+key+b'1')[:self.k]
        c = self.aes_ctr(key, message[:self.k], iv = k1)
        r1 = c + message[self.k:]

        # Round 2
        c = self.aes_ctr(key, r1[self.k:], iv = r1[:self.k])
        r2 = r1[:self.k] + c

        # Round 3
        k3 = self.hash(r2[self.k:]+key+b'3')[:self.k]
        c = self.aes_ctr(key, r2[:self.k], iv = k3)
        r3 = c + r2[self.k:]

        # Round 4
        c = self.aes_ctr(key, r3[self.k:], r3[:self.k])
        r4 = r3[:self.k] + c

        return r4

    def lioness_dec(self, key, message):
        assert len(key) == self.k
        assert len(message) >= self.k * 2

        r4 = message
        r4_short, r4_long = r4[:self.k], r4[self.k:]

        # Round 4        
        r3_long = self.aes_ctr(key, r4_long, iv = r4_short)
        r3_short = r4_short 

        # Round 3
        k2 = self.hash(r3_long+key+b'3')[:self.k]
        r2_short = self.aes_ctr(key, r3_short, iv = k2)
        r2_long = r3_long

        # Round 2
        r1_long = self.aes_ctr(key, r2_long, iv = r2_short)
        r1_short = r2_short 

        # Round 1
        k0 = self.hash(r1_long+key+b'1')[:self.k]
        c = self.aes_ctr(key, r1_short, iv = k0)
        r0 = c + r1_long

        return r0

    # AES-CTR operation
    def xor_rho(self, key, plain):
        assert len(key) == self.k        
        return self.aes_ctr(key, plain)


    # The HMAC; key is of length k, output is of length k
    def mu(self, key, data):
        mac = hmac.new(key, data, digestmod=sha256).digest()[:self.k]
        return mac

    # The PRP; key is of length k, data is of length m
    def pi(self, key, data):
        assert len(key) == self.k
        assert len(data) == self.m

        return self.lioness_enc(key, data)

    # The inverse PRP; key is of length k, data is of length m
    def pii(self, key, data):
        assert len(key) == self.k
        assert len(data) == self.m

        return self.lioness_dec(key, data)

    def small_perm(self, key, data):
        assert len(data) == self.k
        ecb = Cipher("AES-128-ECB")
        enc = ecb.enc(key, b'')
        c = enc.update(data) + enc.finalize()
        return c[:self.k]

    def small_perm_inv(self, key, data):
        assert len(data) == self.k
        ecb = Cipher("AES-128-ECB")
        pad_enc = ecb.enc(key, b'')
        pad_ct = (pad_enc.update(b'\x10' * 16) + pad_enc.finalize())[:16]
        dec = ecb.dec(key, b'')
        p = dec.update(data + pad_ct) + dec.finalize()
        return p[:self.k]

    # The various hashes
    def hash(self, data):
        return sha256(data).digest()

    def get_aes_key(self, s):
        group = self.group
        return bytes(self.hash(b"aes_key:" + group.printable(s))[:self.k])

    def get_aes_key_all(self, s):
        group = self.group
        k = self.hash(b"aes_key:" + group.printable(s))[:self.k]

        num = 3 # (hrho, hmu, htau)
        iv = b"UltrUltrUltrUltr"
        material = self.aes.enc(k, iv).update(b"\x00" * self.k * num)

        return k, [material[self.k*i:self.k*(i+1)] for i in range(num)]

    def derive_key(self, k, flavor):
        assert len(k) == len(flavor) == self.k
        iv = flavor
        m = b"\x00" * self.k
        K = self.aes.enc(k, iv).update(m)
        return K

    def hb(self, k):
        "Compute a hash of alpha and s to use as a blinding factor"
        K = self.derive_key(k, b"hbhbhbhbhbhbhbhb")
        return self.group.makeexp(K)

    def hrho(self, k):
        "Compute a hash of s to use as a key for the PRG rho"
        K = self.derive_key(k, b"hrhohrhohrhohrho")
        return K

    def hmu(self, k):
        "Compute a hash of s to use as a key for the HMAC mu"
        K = self.derive_key(k, b"hmu:hmu:hmu:hmu:")
        return K

    # def hmu2(self, k):
    #    "Compute a hash of s to use as a key for the permutation mu2"
    #    K = self.derive_key(k, b"hmu2:hmu2:hmu2:h")
    #    return K


    def hpi(self, k):
        "Compute a hash of s to use as a key for the PRP pi"
        K = self.derive_key(k, b"hpi:hpi:hpi:hpi:")
        return K

    def htau(self, k):
        "Compute a hash of s to use to see if we've seen s before"
        K = self.derive_key(k, b"htauhtauhtauhtau")
        return K

    def h_body_K(self, k):
        "The Ultrix key to protect the user data."
        K = self.derive_key(k, b"UbodUbodUbodUbod")
        return K

    def h_root_K(self, k):
        "The Ultrix key to protect the root key."
        K = self.derive_key(k, b"UrooUrooUrooUroo")
        return K

    def derive_user_keys(self, k, iv, number=2):
        material = self.aes.enc(k, iv).update(b"\x00" * self.k * number)
        st_ranges = range(0, self.k * number, self.k)


        return [ material[st:st+self.k] for st in st_ranges ]

# All tests

def test_group():
    G = Group_ECC()
    sec1 = G.gensecret()
    sec2 = G.gensecret()
    gen = G.g

    assert G.expon(G.expon(gen, [ sec1 ]), [ sec2 ]) == G.expon(G.expon(gen, [ sec2 ]), [ sec1 ])
    assert G.in_group(G.expon(gen, [ sec1 ]))

def test_gdh_ecc():
    G = Group_ECC()
    x = G.gensecret()
    y = G.expon(G.g, [x])

    r = G.gensecret()
    alpha = G.expon(G.g, [r])
    s = G.expon(alpha, [x])

    assert G.in_group(alpha)
    assert G.in_group(s)
    assert G.validate_shared_secret(s)
    assert G.ddh_verify(y, alpha, s, x)

    # Identity element must be rejected
    identity = G.G.infinite()
    assert not G.in_group(identity)
    assert not G.validate_shared_secret(identity)

    # DDH oracle rejects wrong secret
    wrong_x = G.gensecret()
    assert not G.ddh_verify(y, alpha, s, wrong_x)

    # DDH oracle rejects wrong shared secret
    wrong_s = G.expon(G.g, [G.gensecret()])
    assert not G.ddh_verify(y, alpha, wrong_s, x)

def test_params():
    # Test Init
    params = SphinxParams()
    
    # Test Lioness
    k = b"A" * 16
    m = b"ARG"* 16

    c = params.lioness_enc(k,m)
    m2 = params.lioness_dec(k, c)
    assert m == m2

    # Test CTR
    k = urandom(16)
    c = params.aes_ctr(k, b"Hello World!")
    assert params.aes_ctr(k, c) == b"Hello World!"

    c = params.small_perm(b"\x00"*16, b"\x00"*16)
    c2 = params.small_perm_inv(b"\x00"*16, c)
    assert c2 == b"\x00"*16

    plain = b"Bob"
    k = urandom(16)
    c = params.aes_ctr(k, plain)
    p = params.aes_ctr(k, c)
    assert p == b"Bob"

    plain = b"ACB" * 16
    k = urandom(16)
    iv = urandom(16)
    ctxt = params.aes_cbc_enc(k, plain)
    assert len(ctxt) == len(plain)
    ptxt = params.aes_cbc_dec(k, ctxt)
    assert ptxt == plain

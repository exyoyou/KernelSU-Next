#!/usr/bin/env python3
"""Print what the KernelSU kernel sees in an APK's signing block.

Mirrors kernel/manager/apk_sign.c: lists every block id in the APK Signing
Block and, for the v2 block, the first certificate's size and SHA-256.
Compare SIZE/HASH with KSU_NEXT_MANAGER_SIZE/KSU_NEXT_MANAGER_HASH.

Usage: python3 scripts/youyou_apk_cert.py <app.apk>
"""
import hashlib
import struct
import sys

V2 = 0x7109871A
VERITY_PADDING = 0x42726577
CERT_MAX_LENGTH = 1024


def main(path):
    data = open(path, "rb").read()
    eocd = data.rfind(b"PK\x05\x06")
    if eocd < 0:
        sys.exit("not a zip file")
    cd_off = struct.unpack("<I", data[eocd + 16:eocd + 20])[0]
    if data[cd_off - 16:cd_off] != b"APK Sig Block 42":
        sys.exit("no APK Signing Block (v1-only or unsigned APK)")
    size = struct.unpack("<Q", data[cd_off - 24:cd_off - 16])[0]
    pos, end = cd_off - size, cd_off - 24

    ok = True
    v2_count = 0
    while pos < end:
        pair_len, = struct.unpack("<Q", data[pos:pos + 8])
        block_id, = struct.unpack("<I", data[pos + 8:pos + 12])
        value = data[pos + 12:pos + 8 + pair_len]
        if block_id == V2:
            v2_count += 1
            q = 4 + 4 + 4  # signers seq, signer, signed data lengths
            digests_len, = struct.unpack("<I", value[q:q + 4])
            q += 4 + digests_len + 4  # skip digests, certificates seq length
            cert_len, = struct.unpack("<I", value[q:q + 4])
            cert = value[q + 4:q + 4 + cert_len]
            print("block 0x%08x  v2 signature" % block_id)
            print("SIZE=0x%x (%d bytes)" % (cert_len, cert_len))
            print("HASH=%s" % hashlib.sha256(cert).hexdigest())
            if cert_len > CERT_MAX_LENGTH:
                print("!! cert > %d bytes: kernel rejects it (cert length overlimit)" % CERT_MAX_LENGTH)
                ok = False
        elif block_id == VERITY_PADDING:
            print("block 0x%08x  verity padding (ok)" % block_id)
        else:
            print("!! block 0x%08x  not allowed by the kernel (v3/other signature?)" % block_id)
            ok = False
        pos += 8 + pair_len

    if v2_count != 1:
        print("!! expected exactly 1 v2 block, found %d" % v2_count)
        ok = False
    print("kernel check: %s" % ("OK" if ok else "WILL FAIL"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

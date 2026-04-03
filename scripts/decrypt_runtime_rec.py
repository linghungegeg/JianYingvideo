import argparse
import hashlib
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def decrypt_rec(rec_path: Path, k6: str) -> bytes:
    hex_text = rec_path.read_text(encoding="utf-8").strip()
    key = hashlib.md5(k6.encode("utf-8")).digest()
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(bytes.fromhex(hex_text)) + decryptor.finalize()


def main() -> int:
    parser = argparse.ArgumentParser(description="Decrypt a captured cppreader .rec file")
    parser.add_argument("rec_path", type=Path, help="Path to the .rec file")
    parser.add_argument("k6", help="k6 string used by the runtime")
    parser.add_argument("--out", type=Path, help="Optional output path for decrypted JSON")
    args = parser.parse_args()

    plaintext = decrypt_rec(args.rec_path, args.k6)
    if args.out:
        args.out.write_bytes(plaintext)
    else:
        print(plaintext.decode("utf-8", errors="ignore"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

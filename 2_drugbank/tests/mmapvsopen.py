import mmap
import os
import random
import time

# Parametri
FILE = "bigfile_100MB.bin"
ACCESS_COUNT = 1000  # numero di accessi casuali
CHUNK_SIZE = 1024    # 1 KB per accesso

# -----------------------------------------------------
# 1. Accesso casuale con lettura standard
# -----------------------------------------------------
with open(FILE, "rb") as f:
    t0 = time.time()
    for _ in range(ACCESS_COUNT):
        pos = random.randint(0, os.path.getsize(FILE) - CHUNK_SIZE)
        f.seek(pos)
        data = f.read(CHUNK_SIZE)
t1 = time.time()
print("Random access - open(): {:.4f} s".format(t1 - t0))

# -----------------------------------------------------
# 2. Accesso casuale con mmap
# -----------------------------------------------------
with open(FILE, "rb") as f:
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    t0 = time.time()
    for _ in range(ACCESS_COUNT):
        pos = random.randint(0, len(mm) - CHUNK_SIZE)
        data = mm[pos:pos+CHUNK_SIZE]
    t1 = time.time()
print("Random access - mmap(): {:.4f} s".format(t1 - t0))

mm.close()

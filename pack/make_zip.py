import os
import sys
import time
import zipfile

SRC = r"G:\chaofen5\pack\dist\App"
DST = r"G:\chaofen5\pack\release\全能视像解析终端_便携版_v2.3.0.zip"

if os.path.exists(DST):
    os.remove(DST)

total = 0
locked = []
with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, dirs, files in os.walk(SRC):
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, SRC)
            written = False
            for attempt in range(6):
                try:
                    z.write(fp, rel)
                    written = True
                    break
                except PermissionError:
                    time.sleep(3)
            if written:
                total += 1
            else:
                locked.append(rel)

with zipfile.ZipFile(DST, "r") as z:
    names = z.namelist()
ok = any(n.endswith("PhantomCore/PhantomCore.exe") for n in names)
print("files_written:", total, "locked:", locked)
print("entries:", len(names), "has_engine_exe:", ok)
print("RESULT:", "ZIP_OK" if ok and not locked else "ZIP_BAD")

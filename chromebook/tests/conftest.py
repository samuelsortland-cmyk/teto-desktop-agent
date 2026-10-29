import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CB = os.path.dirname(HERE)
REPO = os.path.dirname(CB)
for p in (REPO, CB):
    if p not in sys.path:
        sys.path.insert(0, p)

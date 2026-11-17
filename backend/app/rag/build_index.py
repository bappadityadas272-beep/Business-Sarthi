"""`python -m app.rag.build_index` (the C-02 acceptance command). See app/rag/index.py."""
import sys

from app.rag.index import main

if __name__ == "__main__":
    sys.exit(main())

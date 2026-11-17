# TEST ONLY scheme fixtures

`schemes_test_only.json` contains **made-up schemes** used only to test the KB loader, the index and the matcher
(C-02, C-03). The names, amounts, rules and `example.org` URLs are fictional and must never be shown to an owner.
The file has `"test_only": true`, and the loader refuses a `test_only` file placed under `data/`.

The real knowledge base is `data/kb/schemes.json`. The team writes it from official pages (checkpoint D-03).

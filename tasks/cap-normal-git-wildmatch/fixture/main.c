#include <stdio.h>
#include <string.h>
#include "wildmatch.h"

int main(int argc, char **argv) {
    unsigned int flags = 0;
    int rc;
    if (argc != 4) {
        fprintf(stderr, "usage: %s MODE TEXT PATTERN\n", argv[0]);
        return 2;
    }
    /* Match Git's upstream t/helper/test-wildmatch.c mode semantics exactly. */
    if (strcmp(argv[1], "wildmatch") == 0) flags = WM_PATHNAME;
    else if (strcmp(argv[1], "iwildmatch") == 0) flags = WM_PATHNAME | WM_CASEFOLD;
    else if (strcmp(argv[1], "pathmatch") == 0) flags = 0;
    else if (strcmp(argv[1], "ipathmatch") == 0) flags = WM_CASEFOLD;
    else { fprintf(stderr, "unknown mode: %s\n", argv[1]); return 2; }
    rc = wildmatch(argv[3], argv[2], flags);
    return rc == WM_MATCH ? 0 : 1;
}

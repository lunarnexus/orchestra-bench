CC ?= cc
CFLAGS ?= -Wall -Wextra -O2

all: wildmatch-cli

wildmatch-cli: main.o wildmatch.o
	$(CC) $(CFLAGS) -o $@ main.o wildmatch.o

main.o: main.c wildmatch.h
wildmatch.o: wildmatch.c wildmatch.h

clean:
	rm -f *.o wildmatch-cli

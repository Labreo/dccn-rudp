## Experiment 5 - Why the window must be smaller than the sequence space
Small sequence numbers (m bits) on a link with 10% data loss and 50% ACK loss. When the window breaks the textbook limit, a retransmitted *old* packet carries the same sequence number as a *new* one the receiver is waiting for; the receiver accepts the wrong data and only the end-to-end SHA-256 check catches it ('corrupted'). 'stalled' means the sender and receiver lost agreement on the window entirely and the transfer was aborted.

| protocol | seq_bits | seq_space | window | rule | correct | corrupted | stalled |
|---|---|---|---|---|---|---|---|
| GBN | 2 | 4 | 3 | safe: N = 2^m - 1 | 6 | 0 | 0 |
| GBN | 2 | 4 | 4 | UNSAFE: N = 2^m | 2 | 0 | 4 |
| SR | 3 | 8 | 4 | safe: N = 2^(m-1) | 6 | 0 | 0 |
| SR | 3 | 8 | 5 | UNSAFE: N > 2^(m-1) | 1 | 5 | 0 |
| SR | 3 | 8 | 6 | UNSAFE: N > 2^(m-1) | 0 | 6 | 0 |

## Experiment 4 - Error detection: CRC-32 vs Internet checksum
20000 random 64-byte frames per error pattern, both codes computed with the project's own implementations. CRC-32 (generator of degree 32) detects all single, double and odd-numbered bit errors and every burst of length <= 32; longer bursts slip through with probability about 2^-32. The Internet checksum is a plain sum, so it cannot see re-ordered 16-bit words or errors that cancel out in the sum.

![checksum](exp4_checksum.png)

| error_pattern | trials | crc32_undetected | inet16_undetected |
|---|---|---|---|
| 1-bit | 20000 | 0 | 0 |
| 2-bit | 20000 | 0 | 646 |
| 3-bit (odd) | 20000 | 0 | 67 |
| burst <= 16 | 20000 | 0 | 0 |
| burst 17-32 | 20000 | 0 | 0 |
| burst 33-64 | 20000 | 0 | 1 |
| random 8-bit | 20000 | 0 | 3 |
| 16-bit word swap | 20000 | 0 | 20000 |
| +1/-1 in two words | 20000 | 0 | 20000 |

/* Native test Worker for Linux and Windows H6 Product paths. No network access. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <unistd.h>
#endif

#define FRAME_CAP 16384

static const uint32_t sha256_round[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

static uint32_t rotate_right(uint32_t value, unsigned int bits) {
    return (value >> bits) | (value << (32 - bits));
}

static void sha256(const unsigned char *input, size_t length, char output[65]) {
    uint32_t state[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    };
    unsigned char padded[FRAME_CAP + 72] = {0};
    memcpy(padded, input, length);
    padded[length] = 0x80;
    size_t total = (length + 9 + 63) & ~(size_t)63;
    uint64_t bit_length = (uint64_t)length * 8;
    for (unsigned int i = 0; i < 8; ++i)
        padded[total - 1 - i] = (unsigned char)(bit_length >> (8 * i));
    for (size_t offset = 0; offset < total; offset += 64) {
        uint32_t words[64];
        for (unsigned int i = 0; i < 16; ++i) {
            size_t at = offset + 4 * i;
            words[i] = ((uint32_t)padded[at] << 24) |
                       ((uint32_t)padded[at + 1] << 16) |
                       ((uint32_t)padded[at + 2] << 8) | padded[at + 3];
        }
        for (unsigned int i = 16; i < 64; ++i) {
            uint32_t a = words[i - 15], b = words[i - 2];
            uint32_t s0 = rotate_right(a, 7) ^ rotate_right(a, 18) ^ (a >> 3);
            uint32_t s1 = rotate_right(b, 17) ^ rotate_right(b, 19) ^ (b >> 10);
            words[i] = words[i - 16] + s0 + words[i - 7] + s1;
        }
        uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
        uint32_t e = state[4], f = state[5], g = state[6], h = state[7];
        for (unsigned int i = 0; i < 64; ++i) {
            uint32_t s1 = rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
            uint32_t choice = (e & f) ^ (~e & g);
            uint32_t first = h + s1 + choice + sha256_round[i] + words[i];
            uint32_t s0 = rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
            uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
            uint32_t second = s0 + majority;
            h = g; g = f; f = e; e = d + first;
            d = c; c = b; b = a; a = first + second;
        }
        state[0] += a; state[1] += b; state[2] += c; state[3] += d;
        state[4] += e; state[5] += f; state[6] += g; state[7] += h;
    }
    for (unsigned int i = 0; i < 8; ++i)
        snprintf(output + 8 * i, 9, "%08x", state[i]);
}

static int read_exact(unsigned char *body, size_t length) {
    while (length) {
#ifdef _WIN32
        DWORD count = 0;
        if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), body, (DWORD)length,
                      &count, NULL) || count == 0) return -1;
#else
        ssize_t count = read(STDIN_FILENO, body, length);
        if (count <= 0) return -1;
#endif
        body += count;
        length -= (size_t)count;
    }
    return 0;
}

static int write_exact(const unsigned char *body, size_t length) {
    while (length) {
#ifdef _WIN32
        DWORD count = 0;
        if (!WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), body, (DWORD)length,
                       &count, NULL) || count == 0) return -1;
#else
        ssize_t count = write(STDOUT_FILENO, body, length);
        if (count <= 0) return -1;
#endif
        body += count;
        length -= (size_t)count;
    }
    return 0;
}

static int read_frame(char body[FRAME_CAP]) {
    unsigned char header[4];
    if (read_exact(header, sizeof header)) return -1;
    size_t length = ((size_t)header[0] << 24) | ((size_t)header[1] << 16) |
                    ((size_t)header[2] << 8) | header[3];
    if (length == 0 || length >= FRAME_CAP) return -1;
    if (read_exact((unsigned char *)body, length)) return -1;
    body[length] = '\0';
    return (int)length;
}

static int write_frame(const char *body) {
    size_t length = strlen(body);
    if (length == 0 || length >= FRAME_CAP) return -1;
    unsigned char header[4] = {
        (unsigned char)(length >> 24), (unsigned char)(length >> 16),
        (unsigned char)(length >> 8), (unsigned char)length,
    };
    return write_exact(header, sizeof header) ||
           write_exact((const unsigned char *)body, length);
}

/* This fixture reads only known, canonical host frames. It is not a JSON parser. */
static int string_field(const char *body, const char *name, char *out, size_t cap) {
    char key[80];
    if (snprintf(key, sizeof key, "\"%s\":\"", name) >= (int)sizeof key) return -1;
    const char *begin = strstr(body, key);
    if (!begin) return -1;
    begin += strlen(key);
    const char *end = strchr(begin, '"');
    if (!end || (size_t)(end - begin) >= cap) return -1;
    memcpy(out, begin, (size_t)(end - begin));
    out[end - begin] = '\0';
    return 0;
}

int main(void) {
    char input[FRAME_CAP], output[FRAME_CAP], attempt[64], nonce[80];
    char correlation[160], digest[65], identity_document[FRAME_CAP];
    if (read_frame(input) < 0 || !strstr(input, "\"kind\":\"start\"")) return 10;
    const char *identity = strstr(input, "\"identity\":{");
    if (!identity) return 11;
    identity += strlen("\"identity\":");
    const char *end = strchr(identity, '}');
    if (!end) return 12;
    int size = snprintf(identity_document, sizeof identity_document,
                        "{\"domain\":\"loushang.worker-launch-identity/v1\",\"value\":%.*s}",
                        (int)(end - identity + 1), identity);
    if (size < 0 || size >= (int)sizeof identity_document - 72) return 13;
    sha256((const unsigned char *)identity_document, (size_t)size, digest);
    if (string_field(identity, "attemptId", attempt, sizeof attempt) ||
        string_field(identity, "sessionNonce", nonce, sizeof nonce)) return 14;
    const char *epoch = strstr(identity, "\"supervisorEpoch\":");
    if (!epoch) return 15;
    unsigned long epoch_value = strtoul(epoch + strlen("\"supervisorEpoch\":"), NULL, 10);
    size = snprintf(output, sizeof output,
                    "{\"attemptId\":\"%s\",\"identityFingerprint\":\"%s\","
                    "\"kind\":\"ready\",\"messageVersion\":1,"
                    "\"protocol\":\"capability.query\",\"protocolVersion\":1,"
                    "\"sessionNonce\":\"%s\",\"supervisorEpoch\":%lu}",
                    attempt, digest, nonce, epoch_value);
    if (size < 0 || size >= (int)sizeof output || write_frame(output)) return 16;
    if (read_frame(input) < 0 || !strstr(input, "\"kind\":\"query\"") ||
        string_field(input, "correlationId", correlation, sizeof correlation)) return 17;
    size = snprintf(output, sizeof output,
                    "{\"correlationId\":\"%s\",\"kind\":\"result\","
                    "\"messageVersion\":1,\"payload\":{\"capabilities\":["
                    "{\"capabilityId\":\"coding.worker.query\",\"descriptorVersion\":1,"
                    "\"facetIds\":[\"query\"]}],\"responseVersion\":1}}",
                    correlation);
    if (size < 0 || size >= (int)sizeof output || write_frame(output)) return 18;
    for (;;) {
        if (read_frame(input) < 0) return 19;
        if (strstr(input, "\"kind\":\"shutdown\""))
            return write_frame("{\"kind\":\"shutdown_ack\",\"messageVersion\":1}") ? 24 : 0;
        if (!strstr(input, "\"kind\":\"query\"") ||
            !strstr(input, "\"operation\":\"invokeReadOnlyFacet\"") ||
            !strstr(input, "\"symbol\":\"review\"") ||
            string_field(input, "correlationId", correlation, sizeof correlation)) return 20;
        size = snprintf(output, sizeof output,
                        "{\"correlationId\":\"%s\",\"kind\":\"result\","
                        "\"messageVersion\":1,\"payload\":{\"responseVersion\":1,"
                        "\"value\":{\"text\":\"Review symbol\"}}}", correlation);
        if (size < 0 || size >= (int)sizeof output || write_frame(output)) return 21;
    }
}

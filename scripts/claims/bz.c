// Exact minimum distance of a linear [n,k] code over GF(q), q in {2,3,4,5,7,8,9}, n <= 128,
// by the Brouwer-Zimmermann algorithm with disjoint information sets (Zimmermann's partial-rank bound).
// Input (stdin): q n k, then k rows of n field elements (integers 0..q-1; GF(4),GF(8): polynomial basis
// over GF(2) with x^2+x+1 / x^3+x+1; GF(9): a+3b for a+b*i, i^2=-1).
// Usage: bz [D [WMAX]]  (WMAX>0: stop after weight-WMAX combinations, print an upper bound 'ub = X')
// A minimum-weight codeword witness is printed as "word: ...".
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXN 128
#define MAXK 128
static int q, n, k, ADD[9][9], MUL[9][9], NEG[9], INV[9];
static unsigned char G[MAXK][MAXN];

static void field(void) {
    int p = (q == 4 || q == 8) ? 2 : (q == 9 ? 3 : q), e = (q == 4) ? 2 : (q == 8 ? 3 : (q == 9 ? 2 : 1));
    for (int a = 0; a < q; a++) for (int b = 0; b < q; b++) {
        if (e == 1) { ADD[a][b] = (a + b) % p; MUL[a][b] = (a * b) % p; continue; }
        int s = 0, pw = 1, x = a, y = b;                      // digit-wise add mod p
        for (int i = 0; i < e; i++) { s += ((x % p + y % p) % p) * pw; x /= p; y /= p; pw *= p; }
        ADD[a][b] = s;
        int ca[3] = {0}, cb[3] = {0}, pr[5] = {0}; x = a; y = b;   // polynomial product, then reduce
        for (int i = 0; i < e; i++) { ca[i] = x % p; x /= p; cb[i] = y % p; y /= p; }
        for (int i = 0; i < e; i++) for (int j = 0; j < e; j++) pr[i + j] = (pr[i + j] + ca[i] * cb[j]) % p;
        if (q == 4) { pr[0] ^= pr[2]; pr[1] ^= pr[2]; }                 // x^2 = x + 1
        if (q == 8) { for (int d = 4; d >= 3; d--) if (pr[d]) { pr[d - 3] ^= 1; pr[d - 2] ^= 1; pr[d] = 0; } } // x^3 = x + 1
        if (q == 9) { pr[0] = (pr[0] - pr[2] + 3) % 3; }                // i^2 = -1
        s = 0; pw = 1; for (int i = 0; i < e; i++) { s += pr[i] * pw; pw *= p; }
        MUL[a][b] = s;
    }
    for (int a = 0; a < q; a++) for (int b = 0; b < q; b++) { if (ADD[a][b] == 0) NEG[a] = b; if (MUL[a][b] == 1) INV[a] = b; }
}

// Systematic matrices for disjoint information sets
static int M, rk[MAXN];
static unsigned char Gam[MAXN][MAXK][MAXN];
static int best, bestw[MAXN];

static void build_sets(void) {
    static unsigned char A[MAXK][MAXN]; memcpy(A, G, sizeof(G));
    int used[MAXN] = {0}; M = 0;
    while (1) {
        int r = 0;                                   // eliminate on unused columns, in order
        static unsigned char B[MAXK][MAXN]; memcpy(B, A, sizeof(A));
        int piv[MAXN]; int np = 0;
        for (int c = 0; c < n && r < k; c++) {
            if (used[c]) continue;
            int pr = -1; for (int i = r; i < k; i++) if (B[i][c]) { pr = i; break; }
            if (pr < 0) continue;
            if (pr != r) for (int j = 0; j < n; j++) { unsigned char t = B[pr][j]; B[pr][j] = B[r][j]; B[r][j] = t; }
            int iv = INV[B[r][c]]; for (int j = 0; j < n; j++) B[r][j] = MUL[B[r][j]][iv];
            for (int i = 0; i < k; i++) if (i != r && B[i][c]) {
                int f = NEG[B[i][c]];
                for (int j = 0; j < n; j++) B[i][j] = ADD[B[i][j]][MUL[f][B[r][j]]];
            }
            piv[np++] = c; r++;
        }
        if (r == 0) break;
        for (int i = 0; i < np; i++) used[piv[i]] = 1;
        memcpy(Gam[M], B, sizeof(B)); rk[M] = r; M++;
        if (M == 1 && r < k) { fprintf(stderr, "generator matrix has rank %d < k=%d\n", r, k); exit(2); }
        int left = 0; for (int c = 0; c < n; c++) left += !used[c];
        if (left == 0) break;
    }
}

// enumerate all combinations of exactly w rows of Gam[m] with nonzero coefficients (first coeff = 1)
static unsigned char part[MAXK + 1][MAXN];
static int coefs[MAXK], rows[MAXK];
static long long leaves;
static void rec(int m, int depth, int w, int start) {
    if (depth == w) {
        int wt = 0; for (int j = 0; j < n; j++) wt += part[depth][j] != 0;
        leaves++;
        if (wt > 0 && wt < best) { best = wt; for (int j = 0; j < n; j++) bestw[j] = part[depth][j]; }
        return;
    }
    for (int i = start; i <= k - (w - depth); i++) {
        int c0 = depth == 0 ? 1 : 1, c1 = depth == 0 ? 1 : q - 1;
        for (int c = c0; c <= c1; c++) {
            const unsigned char *src = part[depth], *row = Gam[m][i]; unsigned char *dst = part[depth + 1];
            for (int j = 0; j < n; j++) dst[j] = ADD[src[j]][MUL[c][row[j]]];
            rec(m, depth + 1, w, i + 1);
        }
    }
}

int main(int argc, char **argv) {
    int D = argc > 1 ? atoi(argv[1]) : 0, WMAX = argc > 2 ? atoi(argv[2]) : 0;   // WMAX>0: quick upper bound only
    if (scanf("%d %d %d", &q, &n, &k) != 3 || n > MAXN || k > MAXK || k > n) { fprintf(stderr, "bad header\n"); return 2; }
    for (int i = 0; i < k; i++) for (int j = 0; j < n; j++) { int x; if (scanf("%d", &x) != 1 || x < 0 || x >= q) { fprintf(stderr, "bad entry\n"); return 2; } G[i][j] = x; }
    field(); build_sets();
    best = n + 1; memset(part[0], 0, sizeof(part[0]));
    for (int m = 0; m < M; m++) for (int i = 0; i < k; i++) {   // weight-1 combos also give an initial upper bound
        int wt = 0; for (int j = 0; j < n; j++) wt += Gam[m][i][j] != 0;
        if (wt < best) { best = wt; for (int j = 0; j < n; j++) bestw[j] = Gam[m][i][j]; }
    }
    int lb = 0;
    for (int w = 1; w <= k; w++) {
        for (int m = 0; m < M; m++) {
            if (w > rk[m]) continue;
            rec(m, 0, w, 0);
            if (D && best < D) { printf("d = %d < %d\n", best, D); goto out; }
        }
        lb = 0; for (int m = 0; m < M; m++) { int t = w + 1 - (k - rk[m]); if (t > 0) lb += t; }
        if (WMAX && w >= WMAX && lb < best) { printf("ub = %d\n", best); goto out; }
        fprintf(stderr, "w=%d lower=%d upper=%d leaves=%lld\n", w, lb, best, leaves);
        if (lb >= best) { printf("d = %d\n", best); goto out; }
        if (D && lb >= D) { printf("d >= %d (upper %d)\n", D, best); goto out; }
    }
    printf("d = %d\n", best);
out:
    printf("word:"); for (int j = 0; j < n; j++) printf(" %d", bestw[j]); printf("\n");
    return 0;
}

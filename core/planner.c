#include "planner.h"

#ifdef __wasm__
#define PL_API(name) __attribute__((export_name(#name)))
#else
#define PL_API(name)
#endif

#ifdef __wasm__
/* No libc in the wasm build, and the compiler may still emit calls to memset. */
void *memset(void *dst, int c, unsigned long n) {
    unsigned char *p = dst;
    while (n--) *p++ = (unsigned char)c;
    return dst;
}
#endif

typedef struct {
    unsigned char row, col, max, rank;
    signed char req; /* index of the prerequisite in the same tree, or -1 */
} Talent;

static struct {
    Talent t[PL_MAX_TREES][PL_MAX_TALENTS];
    int n[PL_MAX_TREES];
    int ntrees;
    int first_level, max_level, per_row, level;
    double table[PL_T_COUNT][PL_MAX_LEVEL + 1];
    double konst[PL_C_COUNT];
    double attr[PL_A_COUNT];
    double mod[PL_M_COUNT];
    char io[PL_IO_SIZE];
} S;

static Talent *get(int tree, int i) {
    if (tree < 0 || tree >= S.ntrees || i < 0 || i >= S.n[tree]) return 0;
    return &S.t[tree][i];
}

/* ------------------------------------------------------------ setup */

PL_API(pl_reset) void pl_reset(void) {
    int i, j;
    for (i = 0; i < PL_MAX_TREES; i++) S.n[i] = 0;
    S.ntrees = 0;
    S.first_level = 10; S.max_level = 60; S.per_row = 5; S.level = 60;
    for (i = 0; i < PL_T_COUNT; i++)
        for (j = 0; j <= PL_MAX_LEVEL; j++) S.table[i][j] = -1.0;
    for (i = 0; i < PL_C_COUNT; i++) S.konst[i] = 0.0;
    for (i = 0; i < PL_A_COUNT; i++) S.attr[i] = 0.0;
    for (i = 0; i < PL_M_COUNT; i++) S.mod[i] = 0.0;
}

PL_API(pl_set_rules) void pl_set_rules(int first_point_level, int max_level, int points_per_row) {
    if (max_level > PL_MAX_LEVEL) max_level = PL_MAX_LEVEL;
    S.first_level = first_point_level;
    S.max_level = max_level;
    S.per_row = points_per_row;
    if (S.level > max_level) S.level = max_level;
}

PL_API(pl_add_tree) int pl_add_tree(void) {
    if (S.ntrees >= PL_MAX_TREES) return -1;
    S.n[S.ntrees] = 0;
    return S.ntrees++;
}

PL_API(pl_add_talent) int pl_add_talent(int tree, int row, int col, int max_rank, int req_index) {
    Talent *t;
    if (tree < 0 || tree >= S.ntrees || S.n[tree] >= PL_MAX_TALENTS) return -1;
    if (max_rank < 1 || max_rank > 9 || row < 1 || req_index >= S.n[tree]) return -1;
    t = &S.t[tree][S.n[tree]];
    t->row = (unsigned char)row; t->col = (unsigned char)col;
    t->max = (unsigned char)max_rank; t->rank = 0;
    t->req = (signed char)(req_index < 0 ? -1 : req_index);
    return S.n[tree]++;
}

/* Prerequisites may point at a talent loaded later (same-row pairs), so they
 * can also be set once the whole tree is in. */
PL_API(pl_set_req) int pl_set_req(int tree, int talent, int req_index) {
    Talent *t = get(tree, talent);
    if (!t || req_index == talent || req_index >= S.n[tree]) return -1;
    t->req = (signed char)(req_index < 0 ? -1 : req_index);
    return 0;
}

/* ------------------------------------------------------------ points */

PL_API(pl_set_level) void pl_set_level(int level) {
    if (level < 1) level = 1;
    if (level > S.max_level) level = S.max_level;
    S.level = level;
}

PL_API(pl_level) int pl_level(void) { return S.level; }

PL_API(pl_points_at_level) int pl_points_at_level(int level) {
    if (level > S.max_level) level = S.max_level;
    if (level < S.first_level) return 0;
    return level - S.first_level + 1;
}

PL_API(pl_tree_points) int pl_tree_points(int tree) {
    int i, sum = 0;
    if (tree < 0 || tree >= S.ntrees) return 0;
    for (i = 0; i < S.n[tree]; i++) sum += S.t[tree][i].rank;
    return sum;
}

PL_API(pl_points_spent) int pl_points_spent(void) {
    int i, sum = 0;
    for (i = 0; i < S.ntrees; i++) sum += pl_tree_points(i);
    return sum;
}

PL_API(pl_points_left) int pl_points_left(void) {
    return pl_points_at_level(S.level) - pl_points_spent();
}

PL_API(pl_required_level) int pl_required_level(void) {
    int spent = pl_points_spent();
    return spent == 0 ? 1 : S.first_level + spent - 1;
}

PL_API(pl_rank) int pl_rank(int tree, int talent) {
    Talent *t = get(tree, talent);
    return t ? t->rank : 0;
}

/* Points spent in rows strictly above `row`. */
static int points_above(int tree, int row) {
    int i, sum = 0;
    for (i = 0; i < S.n[tree]; i++)
        if (S.t[tree][i].row < row) sum += S.t[tree][i].rank;
    return sum;
}

/* A tree is consistent when every learned talent could have been learned in
 * some order: its row is paid for by the rows above it, and its prerequisite
 * is at max rank. */
static int tree_state(int tree) {
    int i;
    for (i = 0; i < S.n[tree]; i++) {
        Talent *t = &S.t[tree][i];
        if (t->rank == 0) continue;
        if (t->rank > t->max) return PL_MAXED;
        if (points_above(tree, t->row) < S.per_row * (t->row - 1)) return PL_ROW_SUPPORT;
        if (t->req >= 0 && S.t[tree][t->req].rank < S.t[tree][t->req].max) return PL_REQ_MISSING;
    }
    return PL_OK;
}

PL_API(pl_validate) int pl_validate(void) {
    int i, r;
    for (i = 0; i < S.ntrees; i++)
        if ((r = tree_state(i)) != PL_OK) return r;
    return PL_OK;
}

PL_API(pl_can_add) int pl_can_add(int tree, int talent) {
    Talent *t = get(tree, talent);
    if (!t) return PL_BAD_INDEX;
    if (t->rank >= t->max) return PL_MAXED;
    if (points_above(tree, t->row) < S.per_row * (t->row - 1)) return PL_ROW_LOCKED;
    if (t->req >= 0 && S.t[tree][t->req].rank < S.t[tree][t->req].max) return PL_REQ_MISSING;
    if (pl_points_left() <= 0) return PL_NO_POINTS;
    return PL_OK;
}

PL_API(pl_can_remove) int pl_can_remove(int tree, int talent) {
    Talent *t = get(tree, talent);
    int i, state;
    if (!t) return PL_BAD_INDEX;
    if (t->rank == 0) return PL_NOT_LEARNED;
    for (i = 0; i < S.n[tree]; i++)
        if (S.t[tree][i].req == talent && S.t[tree][i].rank > 0) return PL_HAS_DEPENDENT;
    t->rank--;
    state = tree_state(tree);
    t->rank++;
    return state == PL_OK ? PL_OK : PL_ROW_SUPPORT;
}

PL_API(pl_add) int pl_add(int tree, int talent) {
    int r = pl_can_add(tree, talent);
    if (r == PL_OK) S.t[tree][talent].rank++;
    return r;
}

PL_API(pl_remove) int pl_remove(int tree, int talent) {
    int r = pl_can_remove(tree, talent);
    if (r == PL_OK) S.t[tree][talent].rank--;
    return r;
}

PL_API(pl_clear_tree) void pl_clear_tree(int tree) {
    int i;
    if (tree < 0 || tree >= S.ntrees) return;
    for (i = 0; i < S.n[tree]; i++) S.t[tree][i].rank = 0;
}

PL_API(pl_clear_all) void pl_clear_all(void) {
    int i;
    for (i = 0; i < S.ntrees; i++) pl_clear_tree(i);
}

/* ------------------------------------------------------------ build strings */

PL_API(pl_io) char *pl_io(void) { return S.io; }

PL_API(pl_export) int pl_export(void) {
    int tree, i, last, len = 0;
    for (tree = 0; tree < S.ntrees; tree++) {
        if (tree) S.io[len++] = '-';
        last = 0; /* always write at least one digit so empty trees read "0" */
        for (i = 0; i < S.n[tree]; i++)
            if (S.t[tree][i].rank) last = i;
        for (i = 0; i <= last && i < S.n[tree]; i++) S.io[len++] = (char)('0' + S.t[tree][i].rank);
    }
    S.io[len] = 0;
    return len;
}

PL_API(pl_import) int pl_import(void) {
    int tree = 0, i = 0, pos, result = PL_OK;
    pl_clear_all();
    for (pos = 0; pos < PL_IO_SIZE && S.io[pos]; pos++) {
        char c = S.io[pos];
        if (c == '-') { tree++; i = 0; continue; }
        if (c < '0' || c > '9' || tree >= S.ntrees || i >= S.n[tree]) { result = PL_BAD_CODE; break; }
        if (c - '0' > S.t[tree][i].max) { result = PL_BAD_CODE; break; }
        S.t[tree][i++].rank = (unsigned char)(c - '0');
    }
    if (result == PL_OK) result = pl_validate();
    if (result != PL_OK) pl_clear_all();
    return result;
}

/* ------------------------------------------------------------ stats */

PL_API(pl_table_set) void pl_table_set(int table, int level, double value) {
    if (table < 0 || table >= PL_T_COUNT || level < 1 || level > PL_MAX_LEVEL) return;
    S.table[table][level] = value;
}

PL_API(pl_table) double pl_table(int table, int level) {
    if (table < 0 || table >= PL_T_COUNT || level < 1 || level > PL_MAX_LEVEL) return -1.0;
    return S.table[table][level];
}

PL_API(pl_const_set) void pl_const_set(int which, double value) {
    if (which >= 0 && which < PL_C_COUNT) S.konst[which] = value;
}

PL_API(pl_attr_set) void pl_attr_set(int which, double value) {
    if (which >= 0 && which < PL_A_COUNT) S.attr[which] = value < 0 ? 0 : value;
}

PL_API(pl_mod_set) void pl_mod_set(int which, double value) {
    if (which >= 0 && which < PL_M_COUNT) S.mod[which] = value;
}

static double floor_pos(double v) { return (double)(long long)(v + 1e-9); }

/* Attribute after its talent percentage, rounded down as the game does. */
static double attr(int which) {
    return floor_pos(S.attr[which] * (1.0 + S.mod[PL_M_STR_PCT + which] / 100.0));
}

/* The first `stat_floor` points of Stamina/Intellect give 1 each, the rest give `per`. */
static double pool(double points, double per) {
    double fl = S.konst[PL_C_STAT_FLOOR];
    return points <= fl ? points : fl + (points - fl) * per;
}

PL_API(pl_derived) double pl_derived(int which) {
    double v;
    switch (which) {
    case PL_D_STR: case PL_D_AGI: case PL_D_STA: case PL_D_INT: case PL_D_SPI:
        return attr(which);
    case PL_D_HEALTH_FROM_STA:
        return floor_pos(pool(attr(PL_A_STA), S.konst[PL_C_HP_PER_STA]) * (1.0 + S.mod[PL_M_HEALTH_PCT] / 100.0));
    case PL_D_MANA:
        v = pl_table(PL_T_BASE_MANA, S.level);
        if (v < 0) return -1.0;
        return floor_pos((v + pool(attr(PL_A_INT), S.konst[PL_C_MANA_PER_INT])) * (1.0 + S.mod[PL_M_MANA_PCT] / 100.0));
    case PL_D_AP:
        return attr(PL_A_STR) * S.konst[PL_C_AP_PER_STR] + attr(PL_A_AGI) * S.konst[PL_C_AP_PER_AGI];
    case PL_D_RAP:
        return attr(PL_A_AGI) * S.konst[PL_C_RAP_PER_AGI];
    case PL_D_CRIT:
        v = pl_table(PL_T_AGI_PER_CRIT, S.level);
        return (v > 0 ? attr(PL_A_AGI) / v : 0.0) + S.mod[PL_M_CRIT];
    case PL_D_SPELL_CRIT:
        v = pl_table(PL_T_INT_PER_SPELL_CRIT, S.level);
        if (v <= 0) return -1.0;
        return attr(PL_A_INT) / v + S.mod[PL_M_SPELL_CRIT];
    case PL_D_ARMOR_FROM_AGI:
        return attr(PL_A_AGI) * S.konst[PL_C_ARMOR_PER_AGI];
    case PL_D_BLOCK_VALUE:
        return S.konst[PL_C_STR_PER_BLOCK] > 0 ? floor_pos(attr(PL_A_STR) / S.konst[PL_C_STR_PER_BLOCK]) : -1.0;
    case PL_D_DPS_FROM_AP:
        return S.konst[PL_C_AP_PER_DPS] > 0 ? pl_derived(PL_D_AP) / S.konst[PL_C_AP_PER_DPS] : 0.0;
    }
    return -1.0;
}

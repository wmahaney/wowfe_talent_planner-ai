/* Native tests for the rules engine: cc -Icore tests/test_planner.c core/planner.c */
#include <stdio.h>
#include <string.h>
#include "planner.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); failures++; } } while (0)

/* A small tree:  row 1: A(5) B(5)   row 2: C(3, needs A)   row 3: D(1) */
static void load(void) {
    int t;
    pl_reset();
    pl_set_rules(10, 60, 5);
    t = pl_add_tree();
    pl_add_talent(t, 1, 1, 5, -1); /* 0 A */
    pl_add_talent(t, 1, 2, 5, -1); /* 1 B */
    pl_add_talent(t, 2, 1, 3, 0);  /* 2 C needs A */
    pl_add_talent(t, 3, 1, 1, -1); /* 3 D */
    t = pl_add_tree();
    pl_add_talent(t, 1, 1, 5, -1);
}

int main(void) {
    int i;
    load();

    /* point budget: first point at 10, one per level, 51 at 60 */
    CHECK(pl_points_at_level(9) == 0);
    CHECK(pl_points_at_level(10) == 1);
    CHECK(pl_points_at_level(60) == 51);
    CHECK(pl_points_at_level(99) == 51);

    pl_set_level(9);
    CHECK(pl_can_add(0, 0) == PL_NO_POINTS);
    pl_set_level(60);

    /* rows and prerequisites */
    CHECK(pl_can_add(0, 2) == PL_ROW_LOCKED);
    for (i = 0; i < 5; i++) CHECK(pl_add(0, 1) == PL_OK);       /* B 5/5 */
    CHECK(pl_add(0, 1) == PL_MAXED);
    CHECK(pl_can_add(0, 2) == PL_REQ_MISSING);                   /* row open, A not maxed */
    for (i = 0; i < 5; i++) CHECK(pl_add(0, 0) == PL_OK);       /* A 5/5 */
    CHECK(pl_add(0, 2) == PL_OK);                                /* C 1/3 */
    CHECK(pl_add(0, 3) == PL_OK);                                /* D, row 3 needs 10 above */
    CHECK(pl_points_spent() == 12);
    CHECK(pl_required_level() == 21);
    CHECK(pl_validate() == PL_OK);

    /* removal keeps the build learnable */
    CHECK(pl_can_remove(0, 0) == PL_HAS_DEPENDENT);              /* C needs A at max */
    CHECK(pl_remove(0, 1) == PL_OK);                             /* 11 above D, one to spare */
    CHECK(pl_can_remove(0, 1) == PL_ROW_SUPPORT);                /* D needs 10 points above */
    CHECK(pl_add(0, 1) == PL_OK);
    CHECK(pl_remove(0, 3) == PL_OK);
    CHECK(pl_can_remove(0, 1) == PL_OK);                         /* now only row 2 needs 5 */
    CHECK(pl_remove(0, 2) == PL_OK);
    CHECK(pl_remove(0, 2) == PL_NOT_LEARNED);
    CHECK(pl_can_add(9, 0) == PL_BAD_INDEX);

    /* level lower than the build needs: left goes negative, nothing is removed */
    pl_set_level(12);
    CHECK(pl_points_left() == 3 - 10);
    CHECK(pl_can_add(1, 0) == PL_NO_POINTS);
    pl_set_level(60);

    /* build strings round-trip */
    pl_add(0, 2);
    CHECK(pl_export() == 5);
    CHECK(strcmp(pl_io(), "551-0") == 0);
    pl_clear_all();
    strcpy(pl_io(), "551-3");
    CHECK(pl_import() == PL_OK);
    CHECK(pl_rank(0, 2) == 1 && pl_rank(1, 0) == 3);
    strcpy(pl_io(), "0001");                                     /* D without support */
    CHECK(pl_import() == PL_ROW_SUPPORT && pl_points_spent() == 0);
    strcpy(pl_io(), "9");
    CHECK(pl_import() == PL_BAD_CODE);
    strcpy(pl_io(), "5x");
    CHECK(pl_import() == PL_BAD_CODE);

    /* derived stats */
    pl_const_set(PL_C_AP_PER_STR, 2); pl_const_set(PL_C_HP_PER_STA, 10);
    pl_const_set(PL_C_MANA_PER_INT, 15); pl_const_set(PL_C_STAT_FLOOR, 20);
    pl_const_set(PL_C_ARMOR_PER_AGI, 2); pl_const_set(PL_C_AP_PER_DPS, 14);
    pl_const_set(PL_C_STR_PER_BLOCK, 20);
    pl_table_set(PL_T_AGI_PER_CRIT, 60, 20.0);
    pl_table_set(PL_T_BASE_MANA, 60, 1512);
    pl_attr_set(PL_A_STR, 100); pl_attr_set(PL_A_AGI, 50);
    pl_attr_set(PL_A_STA, 120); pl_attr_set(PL_A_INT, 60);
    CHECK(pl_derived(PL_D_AP) == 200);
    CHECK(pl_derived(PL_D_HEALTH_FROM_STA) == 20 + 100 * 10);
    CHECK(pl_derived(PL_D_MANA) == 1512 + 20 + 40 * 15);
    CHECK(pl_derived(PL_D_CRIT) == 2.5);
    CHECK(pl_derived(PL_D_SPELL_CRIT) < 0);                      /* no table loaded */
    CHECK(pl_derived(PL_D_BLOCK_VALUE) == 5);
    pl_mod_set(PL_M_STR_PCT, 10); pl_mod_set(PL_M_CRIT, 5);
    CHECK(pl_derived(PL_D_STR) == 110);
    CHECK(pl_derived(PL_D_AP) == 220);
    CHECK(pl_derived(PL_D_CRIT) == 7.5);

    printf(failures ? "%d test(s) failed\n" : "all engine tests passed\n", failures);
    return failures != 0;
}

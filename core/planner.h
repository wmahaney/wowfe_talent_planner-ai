/* WoW Forever talent planner: rules engine.
 *
 * Freestanding C99 (no libc), so the same file builds natively for tests and
 * to WebAssembly for the site. It knows nothing about any particular class:
 * the caller loads trees, rules and stat tables from data, then asks questions.
 */
#ifndef PLANNER_H
#define PLANNER_H

#define PL_MAX_TREES   4
#define PL_MAX_TALENTS 48
#define PL_MAX_LEVEL   100
#define PL_IO_SIZE     1024

/* Result codes for pl_can_add / pl_can_remove / pl_validate / pl_import. */
enum {
    PL_OK = 0,
    PL_BAD_INDEX,      /* no such tree or talent */
    PL_MAXED,          /* already at max rank */
    PL_NO_POINTS,      /* no unspent points at the current level */
    PL_ROW_LOCKED,     /* not enough points in the rows above */
    PL_REQ_MISSING,    /* prerequisite talent is not at max rank */
    PL_NOT_LEARNED,    /* nothing to remove */
    PL_HAS_DEPENDENT,  /* another learned talent requires this one */
    PL_ROW_SUPPORT,    /* lower rows depend on these points */
    PL_BAD_CODE        /* build string could not be parsed */
};

/* Per-level stat tables. */
enum { PL_T_AGI_PER_CRIT = 0, PL_T_INT_PER_SPELL_CRIT, PL_T_BASE_MANA, PL_T_COUNT };

/* Class constants and conversion rules. */
enum {
    PL_C_AP_PER_STR = 0, PL_C_AP_PER_AGI, PL_C_RAP_PER_AGI, PL_C_HP_PER_STA,
    PL_C_MANA_PER_INT, PL_C_STAT_FLOOR, PL_C_ARMOR_PER_AGI, PL_C_AP_PER_DPS,
    PL_C_STR_PER_BLOCK, PL_C_COUNT
};

/* Character attributes (inputs) and percentage modifiers from talents. */
enum { PL_A_STR = 0, PL_A_AGI, PL_A_STA, PL_A_INT, PL_A_SPI, PL_A_COUNT };
enum {
    PL_M_STR_PCT = 0, PL_M_AGI_PCT, PL_M_STA_PCT, PL_M_INT_PCT, PL_M_SPI_PCT,
    PL_M_HEALTH_PCT, PL_M_MANA_PCT, PL_M_CRIT, PL_M_SPELL_CRIT, PL_M_COUNT
};

/* Derived values, see pl_derived(). */
enum {
    PL_D_STR = 0, PL_D_AGI, PL_D_STA, PL_D_INT, PL_D_SPI,
    PL_D_HEALTH_FROM_STA, PL_D_MANA, PL_D_AP, PL_D_RAP, PL_D_CRIT,
    PL_D_SPELL_CRIT, PL_D_ARMOR_FROM_AGI, PL_D_BLOCK_VALUE, PL_D_DPS_FROM_AP,
    PL_D_COUNT
};

/* Setup */
void pl_reset(void);
void pl_set_rules(int first_point_level, int max_level, int points_per_row);
int  pl_add_tree(void);
int  pl_add_talent(int tree, int row, int col, int max_rank, int req_index);
int  pl_set_req(int tree, int talent, int req_index);

/* Level and point budget */
void pl_set_level(int level);
int  pl_level(void);
int  pl_points_at_level(int level);
int  pl_points_spent(void);
int  pl_points_left(void);       /* negative when the level is too low for the build */
int  pl_required_level(void);

/* Spending */
int  pl_rank(int tree, int talent);
int  pl_tree_points(int tree);
int  pl_can_add(int tree, int talent);
int  pl_can_remove(int tree, int talent);
int  pl_add(int tree, int talent);
int  pl_remove(int tree, int talent);
void pl_clear_tree(int tree);
void pl_clear_all(void);
int  pl_validate(void);

/* Build strings: one digit per talent in load order, trees joined by '-'. */
char *pl_io(void);               /* shared buffer of PL_IO_SIZE bytes */
int   pl_export(void);           /* writes to pl_io(), returns length */
int   pl_import(void);           /* reads pl_io(); on failure leaves the build empty */

/* Stats */
void   pl_table_set(int table, int level, double value);
double pl_table(int table, int level);   /* negative = not known */
void   pl_const_set(int which, double value);
void   pl_attr_set(int which, double value);
void   pl_mod_set(int which, double value);
double pl_derived(int which);

#endif

#pragma once
#include <memory>
#include <optional>
#include <vector>
#include "common.h"

// Static facts about one camp group, cached on the first turn.
struct Group {
    bc::map::camp_group handle;
    bitboard spawn;
    std::vector<vec2> tiles;
    int gems = 0;
    int gold = 0;
    float hp = 0.f;        // full-health total
    float strength = 0.f;  // total damage per round when awake
    int camp_count = 0;
    int max_respawn = 0;
    bool monolith = false;
    int reach = 1;         // longest attack range among its fighting camps
    // Dynamic knowledge from our own vision and team broadcasts.
    int respawn_at = 0;    // round the group is back, 0 = assumed up
    bool reward = false;   // monsters dead, capture pending
    int skip_until = 0;    // personal cooldown after a wasted trip
};

// What one visible enemy champion can do to us on its next turn.
// Enemy channels and what breaks them: damage breaks a recall, a stun breaks a
// tribute or a teleport crystal.
namespace Channel {
inline constexpr int NONE = 0, RECALL = 1, TRIBUTE = 2, TELEPORT = 3;
}

struct Foe {
    vec2 pos;
    float weight = 1.f;   // ghosts fade towards 0
    int slack = 0;        // ghosts: extra tiles of reach for unseen movement
    int type = 0;         // champion_type
    int seen = 0;         // round last seen
    float hp = 0.f, max_hp = 1.f, strength = 0.f;
    float spell = 0.f;    // ready single-turn ability damage, 0 if none
    bool ranged = false;
    bool reset = false;   // attack reset ready
    bool dash = false;    // dash ready
    bool stun = false;    // stun ready
    float dash_dmg = 0.f; // DASH_THREAT: ready dash landing damage
    int dash_reach = 0;   // dash range + landing radius
    bool dash_stun = false;
    int gems = 0;
    int channel = 0;      // Channel::kind the enemy is in
    int index = 0;        // into Bot::enemies
};

// An ally as seen at the start of our turn.
struct Mate {
    vec2 pos;
    float hp = 0.f, max_hp = 1.f, power = 0.f;
    int index = 0;  // into Bot::allies
    int gems = 0;
    int type = 0;   // champion_type
};

class Bot {
    bool ready = false;
    int body = 0;          // stable index into the shared-memory claim bytes
    bool paired = false;   // Cassi or Issac: one death kills both halves
    int partner_type = -1, partner_body = 0;
    int bodies = 1;        // allied champion bodies (Cassi & Issac count twice)
    bool ranged = false;
    bc::champion_type kind{};

    std::vector<Group> groups;
    std::vector<std::int16_t> group_at;  // linear tile index -> group id, -1 none
    bitboard terrain;                    // static blocking terrain
    bc::distance_field altar_field;      // distance to the nearest tribute tile
    bc::distance_field spawn_field;      // distance to our spawn
    bc::distance_field here;             // terrain distance from me (lazily, see ensure_here)
    bool here_ready = false;
    std::vector<bc::distance_field> gfield;  // per group: distance from its spawn tiles (static)
    std::vector<char> gfield_ok;
    int gfield_next = 0;
    std::vector<int> field_order;  // build order of the group fields
    bool geo_ready = false;
    std::vector<vec2> geo_centre;  // per group: bounding-box centre of its spawn tiles (OBS_SKIP_FAR)
    std::vector<int> geo_radius;   // per group: Chebyshev radius around that centre
    int vision_r = 8;
    std::unique_ptr<bc::distance_field> move_field;  // scratch buffer for move_to (MOVE_SCRATCH)

    int target = -1;
    int need = 0;          // allies the current target needs alongside us
    int wait_turns = 0;    // turns spent holding for a squad
    int next_eval = 0;     // round of the next full target re-score
    int last_foe_round = -1000;  // last round an enemy champion was in sight
    int standing = 0;            // +1 far ahead, -1 far behind, 0 otherwise
    bool denial = false;         // enemy is closing out the game: deny instead of farm
    std::vector<vec2> tribute_tiles;  // tiles a champion can tribute from
    int detour = 1 << 20;        // extra tiles to bank on the way to the target
    int detour_round = -1000;
    int focus_type = -1, focus_round = -1000;  // FOCUS_STICKY: last enemy we hit
    bc::distance_field detour_field;  // distance from detour_group's spawn tiles
    int detour_group = -1;
    bool mono_dominant = false;  // monoliths hold most of the map's gems
    bool dasher = false;         // we have a dash ability
    bool islands = false;        // some camp group cannot be walked to from our spawn
    bc::distance_field here_dash;  // terrain distance with holes passable (dashers)
    std::uint8_t seen_capture = 0, seen_help = 0;
    int help_fresh = -1000;      // round the help byte last changed
    bool help_mine = false;      // we wrote the current request
    int capture_group = -1;
    int empty_group = -1, empty_turns = 0;  // turns next to a target showing nothing to do
    bool zero_feed = false;   // gem-dead game: protect the gold tiebreak (ZERO_FEED)
    int mono_only = -1;       // every gem group is a monolith (lazy: -1 unknown)
    int contest_turns = 0;    // consecutive turns an enemy stood on our capture region
    int sit_group = -1, sit_since = 0;  // respawn denial (STARVE)
    vec2 sit_tile{};
    bool enemy_field_ready = false;
    bc::distance_field enemy_field;
    int bank_blocked_until = -1;  // no reachable tribute tile until this round
    unsigned last_gems = 0;
    unsigned last_gold = 0;
    bool acted_attack = false;
    float dps_single = 1.f, dps_multi = 1.f;  // this turn's camp damage estimates
    float my_hp = 0.f, my_max = 1.f;
    bool has_monster = false, has_jungle = false;  // camp-fighting emblem passives owned
    std::vector<float> live_hp;     // visible living camp health per group, -1 if unseen
    std::vector<vec2> enemy_pos;
    std::vector<Foe> foes;
    std::vector<bitboard> altar_sq;   // static: tribute squares per altar
    std::vector<char> altar_reach;    // static: a tribute tile is walkable from our spawn
    std::vector<int> altar_hot;  // per altar: last round an enemy was seen near it
    std::vector<Foe> ghosts;  // remembered enemies out of vision (index unused)
    bool use_ghosts = false;  // this turn: we carry a bag worth protecting
    bitboard visible_now;
    std::vector<Mate> mates;
    float burst_here = 0.f;   // enemy burst reaching our tile this turn
    bool outmatched = false;  // nearby enemies out-fight us and our allies
    bitboard danger;          // tiles worth avoiding while walking
    bool danger_ready = true;

    // Per-turn snapshot.
    int round = 0;
    vec2 pos{};
    std::vector<bc::camp> camps;
    std::vector<bc::champion> enemies;
    std::vector<bc::champion> allies;
    std::uint8_t mem[8]{};

    void init();
    void read_memory();
    void write_claim(int group);
    void broadcast_capture(int group);
    void call_help();
    bool answer_help();
    void observe();
    void estimate_dps();
    int group_of(vec2 p) const;
    int tile_index(vec2 p) const;

    void shop();
    std::optional<bc::item_type> next_item() const;
    bool wants_shop() const;

    bitboard blocked_now() const;
    bool move_to(bitboard goals, bool allow_dash = true);
    bool step_away(const std::vector<vec2>& threats);
    bool escape();

    void assess_threat();
    void ensure_danger();
    float burst_at(vec2 p) const;
    float side_power(vec2 at, bool enemy) const;
    float my_burst() const;
    struct FightOutcome {
        float ours0 = 0.f, ours_left = 0.f, theirs0 = 0.f, theirs_left = 0.f;
        int me_dies_at = -1;  // round we die in, -1 if we survive
    };
    FightOutcome simulate_fight(vec2 at, int rounds, bool me_passive) const;

    float my_dps(const Group& g) const;
    float group_hp(int id) const;
    int claims_on(int id) const;
    int required_helpers(const Group& g) const;
    int allies_near(const Group& g) const;
    // Squads wait just outside the group's reach (golems hit at 4, monoliths at 5).
    static int wait_ring(const Group& g) { return std::max(Cfg::SQUAD_WAIT_RING, g.reach + 2); }
    float group_score(int id, int dist, int* req_out = nullptr, float* value_out = nullptr, float* time_out = nullptr) const;
    int choose_target();
    void ensure_here();
public:
    void build_group_fields();
private:
    int vulture_target() const;

    bool dash_strike(const std::vector<vec2>& targets, int min_hits);
    bool fight_enemies(bool kills_only = false);
    bool try_lock_altar();
    bool starve_ok(int g);
    bool camp_trap();
    bool break_channels();
    bool deny();
    bool hand_off_aggro();
    int stun_slot() const;
    bool should_bank() const;
    bool bank();
    bool bank_cached();
    bool farm();
    bool retreat_if_hurt();
    void cast_on_camps(int group);
    void cast_on_camps_unsafe(int group);
    bool attack_camp(int group);
    bool restore_attack();
    int capturer(const Group& g) const;
    bool hand_over(const Group& g) const;
    void use_support_abilities();

public:
    void play_turn();
    float prev_hp = 1e9f;  // our health at the end of our last turn
    bool dead_noted = false;  // this death already marked the groups around it
};

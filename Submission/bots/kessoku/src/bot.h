#pragma once
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
    float hp = 0.f, max_hp = 1.f, strength = 0.f;
    float spell = 0.f;    // ready single-turn ability damage, 0 if none
    bool ranged = false;
    bool reset = false;   // attack reset ready
    bool dash = false;    // dash ready
    bool stun = false;    // stun ready
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
    int bodies = 1;        // allied champion bodies (Cassi & Issac count twice)
    bool ranged = false;
    bc::champion_type kind{};

    std::vector<Group> groups;
    std::vector<std::int16_t> group_at;  // linear tile index -> group id, -1 none
    bitboard terrain;                    // static blocking terrain
    bc::distance_field altar_field;      // distance to the nearest tribute tile
    bc::distance_field spawn_field;      // distance to our spawn
    bc::distance_field here;             // this turn: terrain distance from me

    int target = -1;
    int need = 0;          // allies the current target needs alongside us
    int wait_turns = 0;    // turns spent holding for a squad
    int next_eval = 0;     // round of the next full target re-score
    int last_foe_round = -1000;  // last round an enemy champion was in sight
    int capture_group = -1;
    unsigned last_gems = 0;
    bool acted_attack = false;
    float dps_single = 1.f, dps_multi = 1.f;  // this turn's camp damage estimates
    float my_hp = 0.f, my_max = 1.f;
    bool has_monster = false, has_jungle = false;  // camp-fighting emblem passives owned
    std::vector<float> live_hp;     // visible living camp health per group, -1 if unseen
    std::vector<vec2> enemy_pos;
    std::vector<Foe> foes;
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

    float my_dps(const Group& g) const;
    float group_hp(int id) const;
    int claims_on(int id) const;
    int required_helpers(const Group& g) const;
    int allies_near(const Group& g) const;
    float group_score(int id, int dist, int* req_out = nullptr) const;
    int choose_target();

    bool fight_enemies(bool kills_only = false);
    bool try_lock_altar();
    bool break_channels();
    int stun_slot() const;
    bool should_bank() const;
    bool bank();
    bool farm();
    bool retreat_if_hurt();
    void cast_on_camps(int group);
    bool attack_camp(int group);
    bool restore_attack();
    int capturer(const Group& g) const;
    bool hand_over(const Group& g) const;
    void use_support_abilities();

public:
    void play_turn();
};

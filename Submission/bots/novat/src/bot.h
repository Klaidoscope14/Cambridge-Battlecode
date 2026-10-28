// nova: one Bot per champion process. Turn: observe -> fight / disengage -> deny -> bank -> shop/heal -> join -> farm.
#pragma once
#include <array>
#include <optional>
#include <vector>
#include "config.h"

struct Group {
    bc::map::camp_group handle;
    bitboard spawn;            // capture region
    std::vector<vec2> tiles;
    vec2 center{};
    int gems = 0, gold = 0;
    float hp = 0.f;            // full health of all camps
    float strength = 0.f;      // damage per round of all camps when awake
    int reach = 1;
    int camps = 0;
    bool monolith = false;
    int owner = 0;             // +1 ours, -1 theirs, 0 contested (static, from walk distances)
    // dynamic
    float live_hp = -1.f;      // visible camps' health this turn (-1 = unseen)
    int alive_seen = 0;        // visible living camps this turn
    bool reward = false;       // camps dead, capture pending
    int respawn_at = 0;
    int skip_until = 0;
};

struct Unit {                  // a visible ally or enemy champion (or a remembered enemy)
    vec2 pos{};
    float hp = 0.f, max_hp = 1.f;
    float dps = 0.f;           // basic damage per round (strength)
    float spell = 0.f;         // ready single-turn spell damage
    int type = -1;
    int gems = 0;
    int reach = 1;
    bool tributing = false;
    int index = -1;            // into Bot::enemy_handles / ally_handles
    int seen = 0;              // round last seen (memory)
    float weight = 1.f;        // memory fades
};

class Bot {
public:
    void play_turn();
    void trace() const;

private:
    // ---- world (world.cpp) ----
    void init();
    void observe();
    void read_memory();
    void write_byte(int at, std::uint8_t v);
    bool move_to(bitboard goals, bool flee = false, const bc::distance_field* far = nullptr);
    const bc::distance_field* group_field(int g);
    bitboard blocked() const;
    int group_of(vec2 spawn_tile) const;
    float burst_at(vec2 p) const;
    bool mono_danger(vec2 p) const;
    bool restore_attack();   // damage visible/remembered enemies can land on p next turn
    bool on_spawn() const { return ally_spawn.is_set(pos); }

    // ---- farming (farm.cpp) ----
    void rescore();
    int rivals(int g) const;
    bool engaged() const;
    float score(int g, int dist, bool* needs_help, bool lead = false) const;
    bool farm();
    bool attack_group_camp(int g);
    void claim(int g);
    int path_to(int g);
    int helpers_at(int g) const;
    int claimers(int g) const;
    int needed_helpers(int g) const;
    bool capturing() const;
    void estimate_camp_dps();
    void cast_on_camps(int g);

    // ---- economy (econ.cpp) ----
    bool should_bank() const;
    bool bank();
    bool altar_safe(vec2 a) const;
    void shop();
    std::optional<bc::item_type> next_item() const;
    bool go_home();
    bool deny_tribute();
    void place_ward();

    // ---- fights (fight.cpp) ----
    void assess();
    bool fight();
    bool engage();
    bool disengage();
    bool join();
    bool cast_spells();
    bool attack_best();
    bool capturing_soon() const;

    bool ready_ = false;
    int W = 0, H = 0, round = 0, body = 0, bodies = 1;
    bc::champion_type kind{};
    bool ranged = false;
    vec2 pos{};
    float my_hp = 0.f, my_max = 1.f;
    bitboard ally_spawn, enemy_spawn, terrain, tribute, altars;
    std::vector<vec2> altar_tiles;
    bc::distance_field spawn_field, enemy_field, altar_field, here;
    int here_round = -100;
    std::vector<Group> groups;
    std::vector<std::int16_t> group_at;
    std::vector<std::optional<bc::distance_field>> gfield;  // per group: distance from its capture tiles
    std::array<std::uint8_t, 8> mem{};

    std::vector<bc::champion> ally_handles, enemy_handles;
    struct CampView { vec2 pos; int group = -1; float hp = 0.f; bool dead = true, awake = false; };
    std::vector<CampView> cv;
    bitboard vis;
    std::vector<int> dead_types;
    int fields_built_round = -1;
    int map_mode = 0;              // +1 fight map, -1 race map, 0 normal (MAP_MODES)
    int wait_turns = 0;            // turns spent on the squad wait ring for the current target   // enemy champion types dead at the last check                  // tiles in sight this turn      // camps[i] read once per turn (each engine query costs fuel)
    std::vector<Unit> allies, enemies, ghosts;
    int target = -1, last_score_round = -100, target_since = 0;
    float target_score = 0.f;
    int last_ward = -100;
    float last_hp = 0.f;
    bool has_jungle = false;
    float camp_dps = 10.f;        // our damage per round on camps (basic + spells / cooldown)
    int enemies_dead = 0;
    int gem_gap = 0;              // our tributed - theirs

    // fight state for this turn
    float ratio = 1.f;            // local power ours / theirs
    int nearest_enemy = 99;
    bool acted = false;
};

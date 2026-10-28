#!/usr/bin/env python3
"""Rebuild Submission/bots/novat = nova + silent fuel profiling (avg/max per stage, printed once at r400)."""
import os as _os
SUB = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../..'))  # Submission/
import os, shutil
B = SUB + '/bots'
shutil.rmtree(f'{B}/novat', ignore_errors=True)
shutil.copytree(f'{B}/nova', f'{B}/novat', ignore=shutil.ignore_patterns('.cambc'))
S = f'{B}/novat/src'
def ed(f, pairs):
    s = open(f'{S}/{f}').read()
    for a, b in pairs:
        assert a in s, (f, a); s = s.replace(a, b, 1)
    open(f'{S}/{f}', 'w').write(s)
ed('config.h', [('#pragma once', '#pragma once\n#define NOVA_TRACE 1'),
    ('// Last decision stage', 'inline std::uint64_t g_prof[20], g_cnt[20], g_max[20], g_last;\ninline void CK(int i) { const auto f = cambc::fuel_remaining(); if (g_last >= f) { g_prof[i] += g_last - f; if (g_last - f > g_max[i]) g_max[i] = g_last - f; } ++g_cnt[i]; g_last = f; }\n// Last decision stage')])
ed('turn.cpp', [('    g_stage = "observe";\n    observe();', '    g_last = bc::fuel_remaining();\n    g_stage = "observe";\n    observe();\n    CK(0);'),
    ('    assess();\n', '    assess();\n    CK(2);\n'),
    ('    g_stage = "fight";\n    if (fight()) {', '    g_stage = "fight";\n    const bool fought = fight();\n    CK(3);\n    if (fought) {'),
    ('    if (deny_tribute()) return;', '    if (deny_tribute()) return;\n    CK(4);'),
    ('    if (should_bank() && bank()) return;', '    { const bool sb = should_bank(); CK(5); if (sb && bank()) { CK(6); return; } CK(6); }'),
    ('    if (go_home()) return;', '    { const bool h = go_home(); CK(7); if (h) return; }'),
    ('    if (join()) return;', '    { const bool j = join(); CK(8); if (j) return; }'),
    ('    farm();\n    place_ward();', '    farm();\n    CK(9);\n    place_ward();\n    CK(10);'),
    ('#ifdef NOVA_TRACE\n', '#ifdef NOVA_TRACE\n    static bool done = false;\n    if (round >= 400 && !done) {\n        done = true;\n        std::cout << "P " << bc::to_string(kind);\n        static const char* nm[] = {"observe","-","assess","fight","deny","should_bank","bank","home","join","farm","ward","o:mem","o:allies","o:enemies","o:ghosts","o:camps","rescore","r:fields","move","m:search"};\n        for (int i = 0; i < 20; ++i) if (g_cnt[i]) std::cout << " " << nm[i] << "=" << g_prof[i] / g_cnt[i] << "/" << g_max[i];\n        std::cout << std::endl;\n    }\n    return;\n')])
s = open(f'{S}/world.cpp').read(); i = s.index('void Bot::observe() {'); b = s[i:]
for a, c in [('    read_memory();', '    read_memory();\n    CK(11);'), ('    enemy_handles.clear();', '    CK(12);\n    enemy_handles.clear();'),
             ('    // Memory of unseen enemies', '    CK(13);\n    // Memory of unseen enemies'), ('    // Camps from two bitboards', '    CK(14);\n    // Camps from two bitboards'),
             ('    // Partial sight', '    CK(15);\n    // Partial sight')]:
    assert a in b, a; b = b.replace(a, c, 1)
open(f'{S}/world.cpp', 'w').write(s[:i] + b)
print('novat rebuilt from nova')

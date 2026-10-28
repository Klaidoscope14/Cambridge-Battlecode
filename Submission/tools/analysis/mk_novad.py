#!/usr/bin/env python3
"""Rebuild Submission/bots/novat = nova + death log: the last 6 turns before each death (stage, hp, ratio, enemies)."""
import os as _os
SUB = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../..'))  # Submission/
import shutil
B = SUB + '/bots'
shutil.rmtree(f'{B}/novat', ignore_errors=True)
shutil.copytree(f'{B}/nova', f'{B}/novat', ignore=shutil.ignore_patterns('.cambc'))
S = f'{B}/novat/src'
def ed(f, pairs):
    s = open(f'{S}/{f}').read()
    for a, b in pairs:
        assert a in s, (f, a); s = s.replace(a, b, 1)
    open(f'{S}/{f}', 'w').write(s)
ed('config.h', [('#pragma once', '#pragma once\n#define NOVA_TRACE 1\n#include <string>\n#include <deque>'),
    ('// Last decision stage', 'inline std::deque<std::string> g_log; inline bool g_dead_logged = false;\n// Last decision stage')])
ed('turn.cpp', [('    if (!me.is_alive()) {', '    if (!me.is_alive()) {\n        if (!g_dead_logged) { g_dead_logged = true; std::cout << "DEATH " << bc::to_string(kind) << " r" << round << "\\n"; for (auto& l : g_log) std::cout << "  " << l << "\\n"; std::cout << std::flush; }'),
    ('#ifdef NOVA_TRACE\n', '''#ifdef NOVA_TRACE
    {
        g_dead_logged = false;
        int al = 0, en = 0;
        for (const auto& a : allies) al += cheb(a.pos, pos) <= Nv::SKIRMISH;
        for (const auto& e : enemies) en += cheb(e.pos, pos) <= Nv::SKIRMISH;
        char buf[240];
        std::snprintf(buf, sizeof buf, "r%d %s hp %d/%d ratio %.2f ne %d allies6 %d enemies6 %d ghosts %d gems %u tgt %d", round, g_stage,
                      static_cast<int>(my_hp), static_cast<int>(my_max), ratio, nearest_enemy, al, en, static_cast<int>(ghosts.size()), bc::self().gem_count(), target);
        g_log.push_back(buf);
        if (g_log.size() > 6) g_log.pop_front();
    }
    return;
''')])
print('novat (death log) rebuilt from nova')

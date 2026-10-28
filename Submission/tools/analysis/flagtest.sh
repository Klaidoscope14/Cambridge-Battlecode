#!/bin/bash
# flagtest.sh TAG FLAG "MAPS..." : bots/nv_TAG = nova0 with Nv::FLAG on; head-to-head vs nova0 on MAPS, throughput vs starter-cpp.
set -e
cd "$(dirname "$0")/../.."
export PATH=/opt/anaconda3/bin:$PATH AB_OUT=$HOME/.cache/kessoku_ab
T=$1; F=$2; M=$3
rm -rf bots/nv_$T; cp -r bots/nova0 bots/nv_$T; rm -rf bots/nv_$T/.cambc
sed -i.bak "s/inline constexpr bool $F = false;/inline constexpr bool $F = true;/" bots/nv_$T/src/config.h && rm -f bots/nv_$T/src/config.h.bak
grep -q "bool $F = true" bots/nv_$T/src/config.h
cambc build nv_$T >/dev/null 2>&1; cambc build nova0 >/dev/null 2>&1
rm -rf $AB_OUT/h2h_$T $AB_OUT/thr_$T
python3 tools/ab.py h2h_$T nv_$T nova0 $M | tail -1
python3 tools/ab.py thr_$T nv_$T starter-cpp 00eight 02fields 01shortcut 00lanes 02the_pack 01gold_rush | tail -1
python3 tools/analysis/thr.py ${BASE:-thr_nova} thr_$T

#!/usr/bin/env python3
"""Forge-LLM v0.2: offline candidate shortlist, NOT a production scheduler.

Usage:
  python forge_llm_selector.py --task code_repo --free-vram 24 --runtime llama.cpp
  python forge_llm_selector.py --task asr --free-vram 4 --active 2 --context 4096

When a profile has no measured evidence, deployment_authorized always remains false.
"""
import argparse, json, pathlib

CATALOG_PATH = pathlib.Path(__file__).with_name('forge_llm_catalog_2026-11-03.json')

def select(catalog, task, free_vram, active=1, context=4096, runtime=None, modalities=None, language=None):
    tiers = [t for t in catalog['vram_tiers_gb'] if t <= free_vram]
    if not tiers: return {'error':'insufficient_free_vram_for_catalog','candidates':[]}
    tier = max(tiers)
    tasks = {r['task_id']: r for r in catalog['tasks']}
    if task not in tasks:
        return {'error':'unknown_task','known_tasks':sorted(tasks),'candidates':[]}
    by_alias = {m['alias']:m for m in catalog['models']}
    candidates=[]
    for rank, c in enumerate(tasks[task]['candidates_by_vram_gb'][str(tier)],1):
        m = by_alias[c['alias']]
        if m['estimated_min_vram_tier_gb'] > free_vram:
            continue
        if runtime and runtime not in m['candidate_runtimes']:continue
        if modalities and any(q not in m['input_modalities'] for q in modalities):continue
        if language and m['verified_languages'] and language not in m['verified_languages']:continue
        flags=[]
        if language and not m['verified_languages']:flags.append('language_support_requires_test')
        if c['fit']=='tight_or_offload':flags.append('tight_quant_or_offload')
        if c['fit']=='low_quality_fallback':flags.append('low_quality_expected')
        if active>1:flags.append('active_concurrency_not_memory_benchmarked')
        if context>4096:flags.append('context_above_reference_not_memory_benchmarked')
        flags.extend(['runtime_support_not_probed','checkpoint_not_pinned','peak_vram_not_measured','license_not_approved','quality_not_benchmarked'])
        candidates.append({'rank':rank,'alias':m['alias'],'model_id':m['model_id'],
           'reference_precision':m['reference_precision'],'architecture':m['architecture'],
           'estimated_min_vram_tier_gb':m['estimated_min_vram_tier_gb'],
           'source_url':m['source_url'],'license_gate':m['license_gate'],
           'availability':'cataloged_official_repo',
           'fit_status':c['fit'],'blockers':flags,
           'deployment_authorized':False})
    return {'task':task,'input':{'free_vram_gb':free_vram,'nominal_tier_gb':tier,'active_requests':active,
      'context_tokens':context,'runtime':runtime,'input_modalities':modalities,'language':language},
      'results_type':'provisional_shortlist_not_schedule_decision',
      'candidates':candidates,'fallback':'queue_or_escalate_to_larger_node' if not candidates else 'benchmark_and_license_gate',
      'production_policy':'DENY until exact model quant and runtime on target GPU have measured peak VRAM and passed quality, license and p95 SLO gates'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--catalog',type=pathlib.Path,default=CATALOG_PATH)
    ap.add_argument('--task',required=True)
    ap.add_argument('--free-vram',type=float,required=True)
    ap.add_argument('--active',type=int,default=1)
    ap.add_argument('--context',type=int,default=4096)
    ap.add_argument('--runtime')
    ap.add_argument('--modality',action='append',default=[])
    ap.add_argument('--language',help='ISO code, e.g. uk; excludes models with explicit incompatible language lists')
    args=ap.parse_args()
    if args.active<1 or args.context<1 or args.free_vram<0: ap.error('positive resource values required')
    d=json.loads(args.catalog.read_text(encoding='utf-8'))
    print(json.dumps(select(d,args.task,args.free_vram,args.active,args.context,args.runtime,args.modality or None,args.language),ensure_ascii=False,indent=2))
if __name__=='__main__':main()

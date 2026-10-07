"""Internal AI coverage proxy. NOT certified correctness or a prize payout gate."""
import argparse
import math
import os
import time
from pathlib import Path
from app import invoke_agent
from .core import read, write
from .pipeline import run


def score_case(report, assessment, criteria):
    expected={c['id'] for c in criteria}
    rows=assessment['criteria']
    if len(rows)!=len(expected) or {r['id'] for r in rows}!=expected:
        raise ValueError('Assessor changed rubric IDs')
    final=report['rounds'][-1]
    properties={p['id'] for p in final['candidate']['properties']}
    supported={row['finding']['property_id'] for row in final.get('findings',[])
               if row['check']['status']=='supported_model_counterexample'}
    if final.get('proof_check',{}).get('status')=='proved': supported |= properties
    coverage=0; evidence=0
    for row in rows:
        if not isinstance(row['covered'],bool): raise ValueError('Invalid assessor value')
        if row['covered'] and (not row['property_id'] or row['property_id'] in properties):
            coverage+=1
            if row['property_id'] in supported: evidence+=1
    return {'semantic_coverage_proxy':coverage/len(expected), 'covered_formal_evidence':evidence/len(expected),
            'score':100*(.6*coverage+.4*evidence)/len(expected)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',required=True); parser.add_argument('--output',required=True)
    parser.add_argument('--reports',nargs='*',help='Assess existing reports in rubric case order instead of making new pipeline calls')
    args=parser.parse_args(); root=Path(args.output)
    if root.exists(): raise ValueError('Use a new output directory')
    root.mkdir(parents=True)
    rubric=read('.yukon/rubric.json'); scores=[]
    if args.reports and len(args.reports)!=len(rubric['cases']): raise ValueError('Need one report per rubric case')
    for i,case in enumerate(rubric['cases']):
        folder=root/('case-'+str(i+1))
        report=read(args.reports[i]) if args.reports else run(read(case['input']),folder/'pipeline',rounds=2,model=args.model,timeout=360)
        if report['input']!=read(case['input']): raise ValueError('Report input differs from protected fixture')
        # Independent context: never accept a submitter-supplied assessment.
        assessment=invoke_agent('general_assessor',{'rubric':case['criteria'],'report':report},folder/'assessment',360,model=args.model)
        scored=score_case(report,assessment,case['criteria']); scores.append(scored)
    value=sum(s['score'] for s in scores)/len(scores)
    if not math.isfinite(value): raise ValueError('Non-finite score')
    result={'score':value,'metrics':{'cases':scores,'grading':'experimental AI coverage proxy; no certified intent fidelity',
                                  'public_smoke_cases':True,'creator_approval':'pending','contract_correspondence':'not_proved'}}
    write(root/'score.json',result); write('.yukon/score.json',result)
    print('Internal proxy score: '+str(round(value,2)))


if __name__=='__main__': main()

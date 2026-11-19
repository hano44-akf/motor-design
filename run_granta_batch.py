"""Sequential official API exports followed by validation and library rebuild."""
from pathlib import Path
import json
import subprocess
import sys
from datetime import datetime, timezone
from collections import Counter
from collect_materials import collect
from verify_library import verify

ROOT = Path(__file__).resolve().parent

def run(batch):
    plan = json.loads((batch / 'plan.json').read_text(encoding='utf-8'))
    status = {'status': 'running', 'requested_count': sum(g['count'] for g in plan),
              'started_utc': datetime.now(timezone.utc).isoformat(), 'groups': []}
    def save():
        temp = batch / 'status.tmp'
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(batch / 'status.json')
    save()
    try:
        for index, group in enumerate(plan):
            current = {'source': group['source'], 'requested_count': group['count'],
                       'output': group['output'], 'status': 'running'}
            status['groups'].append(current)
            save()
            print(f'GROUP {index+1}/{len(plan)}: {Path(group["source"]).name} ({group["count"]})', flush=True)
            with (batch / f'{index:02d}_export.log').open('a', encoding='utf-8') as log:
                result = subprocess.run([sys.executable, '-u', str(ROOT / 'export_granta.py'),
                    group['output'], group['table'], group['source']], cwd=ROOT,
                    stdout=log, stderr=subprocess.STDOUT)
            report_path = Path(group['output']) / 'report.json'
            report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
            current['exported_count'] = sum(r['status'] == 'exported' for r in report.get('results', []))
            current['status'] = report.get('status', 'missing_report')
            save()
            if result.returncode or current['status'] != 'all_requested_exported':
                raise RuntimeError('Export stopped; inspect ' + str(batch / f'{index:02d}_export.log'))
        library = collect()
        verify(library)
        counts = Counter()
        missing = []
        for group in plan:
            report = json.loads((Path(group['output']) / 'report.json').read_text(encoding='utf-8'))
            if set(report['requested_names']) != {r['name'] for r in report['results'] if r['status'] == 'exported'}:
                raise ValueError('Requested/exported name mismatch')
            for item in report['results']:
                for curve in item.get('curves', []):
                    counts[curve['kind']] += curve['point_count']
                if not item.get('curves'):
                    missing.append(item['name'])
        status.update(status='complete', library_directory=str(library), curve_point_counts=dict(counts),
                      materials_without_recognized_curves=missing,
                      completed_utc=datetime.now(timezone.utc).isoformat())
        (library / 'README_KO.md').write_text(
            '# Motor-CAD 재질 원시 데이터 통합\n\n'
            f'이번 첨부 {status["requested_count"]}개 재질을 공식 API로 추출하고 기존 데이터와 통합했습니다.\n'
            f'이번 곡선 점 수: {dict(counts)}\n\n'
            '`materials_raw.json`: 통합 원시 필드·배열·출처·해시.\n'
            '`catalog.csv`: 재질 목록. `raw_fields.csv`: 모든 원시 필드.\n'
            '`indexed_values.csv`: 모든 배열 값. `raw/`: 원본 파일.\n'
            '`verification.json`: 해시·원문 필드·배열 보존 검사 결과.\n\n'
            '범위는 사용자가 제공한 목록입니다. 전체 Granta 라이브러리의 완전성을 뜻하지 않습니다.\n'
            '동일 이름의 다른 데이터는 별도 버전으로 보존했습니다. 원시 단위·추정값 주석을 유지했습니다.\n'
            '단위 정규화·보간·물리 정확도 검증은 별도 단계입니다.\n', encoding='utf-8')
        save()
        print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    except Exception as exc:
        status.update(status='failed', error=str(exc))
        save()
        raise

if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())

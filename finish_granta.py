"""Finish an active export by verifying it and rebuilding the raw library."""
from pathlib import Path
import json
import sys
import time
import hashlib
from collections import Counter
from collect_materials import collect, parse_mdb, summarize
from verify_library import verify

def finish(run):
    print('Waiting for export completion: ' + str(run), flush=True)
    while True:
        try:
            report = json.loads((run / 'report.json').read_text(encoding='utf-8'))
        except (ValueError, FileNotFoundError):
            time.sleep(10)
            continue
        if report.get('status') in ('all_requested_exported', 'failed', 'stopped_on_error'):
            break
        time.sleep(15)
    exported = [r for r in report['results'] if r['status'] == 'exported']
    result = {'requested': report['requested_count'], 'exported': len(exported),
              'export_status': report['status'], 'missing_names': sorted(set(report['requested_names']) - {r['name'] for r in exported})}
    points = 0
    curve_missing = []
    for item in exported:
        data = (run / item['file']).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Hash mismatch: ' + item['name'])
        _, sections, _ = parse_mdb(data)
        selected = [s for s in sections if s['name'] == item['name']]
        if len(selected) != 1:
            raise ValueError('Name mismatch')
        _, arrays, curves, warnings = summarize(selected[0])
        magnet = [c for c in curves if c['kind'] == 'magnet_bh']
        if not magnet:
            curve_missing.append(item['name'])
        else:
            if not magnet[0]['indices_match']:
                raise ValueError('Curve mismatch: ' + item['name'])
            points += magnet[0]['point_count']
    result.update(total_magnet_bh_points=points, materials_without_bh_curve=curve_missing)
    library = collect()
    verify(library)
    result['library_directory'] = str(library)
    (run / 'completion.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (library / 'README_KO.md').write_text(
        '# Motor-CAD 원시 재질 데이터 통합\n\n'
        f'제공된 Granta 목록 {result["requested"]}개 중 {result["exported"]}개 추출.\n'
        f'자석 B–H 총 {points}점. 곡선 없는 재질 {len(curve_missing)}개.\n\n'
        '`materials_raw.json`: 일반 MDB 및 성공한 공식 Granta API 출력의 모든 원시 필드.\n'
        '`catalog.csv`: 내용별 재질 목록. 동일 이름의 다른 내용은 별도 보존.\n'
        '`raw_fields.csv`, `indexed_values.csv`: 원시 필드와 배열 값.\n'
        '`raw/`: 원본 파일 바이트 및 API 출력 보관.\n'
        '`verification.json`: 원본 해시·필드·배열 대조 결과.\n\n'
        '이름 목록은 사용자가 제공한 표를 기준으로 합니다. 전체 Granta DB의 완전성을 뜻하지 않습니다.\n'
        '다른 GDB는 아직 원본 보관 단계입니다. 단위 정규화·보간·물리 정확도 검증은 수행하지 않았습니다.\n'
        '공급자가 추정한 물성과 Motor-CAD 파생 파라미터의 원문 주석을 보존합니다.\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

if __name__ == '__main__':
    finish(Path(sys.argv[1]))

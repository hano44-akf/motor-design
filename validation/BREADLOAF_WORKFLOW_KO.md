# Breadloaf 개발용 단계별 실행

이 명령은 AI 에이전트 없이 실행할 수 있다. 범용 모터 설계 엔진이나 GUI 연결 완료를 뜻하지 않는다. 고정 템플릿의 Breadloaf 리플 개발 범위이며 전압·효율·포화·감자·제조 제약을 포함한 전체 목표 최적화는 미완료다. Flat 리플은 보류한다.

명령의 `python`에는 현재 프로젝트 Python 실행 파일을 사용한다:
`C:/Users/jo061/AppData/Local/Python/pythoncore-3.14-64/python.exe`.

## 상태와 검토

```powershell
python validation/breadloaf_workflow.py status --batch outputs/breadloaf_current_feedback_20261104
python validation/breadloaf_workflow.py review --batch outputs/breadloaf_current_feedback_20261104
```

두 명령은 해석을 시작하지 않는다. 검토는 입력·예측 해시를 대조하며 원시 결과를 수정하지 않는다. 토크 잔차가 작아도 허용오차를 임의 추가해 합격시키지 않는다.

## 새 탐색과 검증 배치

새 출력 폴더를 지정한다. 아래는 이전 개발 비교점을 재현하는 예시다.

```powershell
python validation/breadloaf_workflow.py search --seed-snapshot outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json --output outputs/breadloaf_new_search --target-electromagnetic-torque 0.5 --max-line-peak-current 40 --iterations 10
python validation/breadloaf_workflow.py prepare --study outputs/breadloaf_new_search --model outputs/spm_ripple_validation_v2_20261103_140824/surface_breadloaf_13.mot --output outputs/breadloaf_new_verification
```

`search`는 슬롯 입구·극호·reduction만 탐색하며 원시 선형 자기회로 모델로 평가한다. 지정 목표는 전자기 토크이고 축토크가 아니다. 이 두 단계는 Native 해석을 실행하지 않는다. 예측 20% 이하가 나와도 실제 합격으로 간주하지 않는다. `prepare`는 각 후보에 대한 입력·예측 해시와 새 전류를 고정한다.

## Native 시작과 완료 확인

```powershell
python validation/breadloaf_workflow.py start --batch outputs/breadloaf_new_verification
python validation/breadloaf_workflow.py status --batch outputs/breadloaf_new_verification
```

`start`만 Motor-CAD 작업을 실행하며 PID·예상 시간·로그를 저장하고 즉시 반환한다. 전역 잠금과 건별 시간 제한은 기존 실행기에 맡긴다. 이미 시작된 배치의 중복 실행과 Flat 배치는 거부한다. 완료 후 `review`로 결과를 확인한다. 기존 사용자의 Motor-CAD 창은 조작하지 않는다.

## 토크 보정

```powershell
python validation/breadloaf_workflow.py feedback --batch outputs/breadloaf_new_verification --output outputs/breadloaf_new_feedback
```

이 명령은 기존 FEA를 사용해 전류 보정안만 준비한다. 실행하려면 별도로 `start`해야 한다. 기본 보정 예산은 1회이며, 예산이 끝나면 새 보정 배치를 만들지 않는다. 예산을 늘리려면 `--max-corrections`를 명시해야 한다. 보정 데이터는 같은 후보와 제어·온도 조건에만 사용한다. 리플값을 임의 보정하거나 새 형상 독립 검증으로 재집계하지 않는다.

실제 2026-11-04 결과는 `outputs/breadloaf_current_feedback_20261104/COMPLETION_REVIEW_KO.md`를 참고한다.

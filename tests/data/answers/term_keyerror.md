TYPE: work
ANSWER: KeyError: 존재하지 않는 키 `w`를 참조하기 때문입니다. `dict.get` 또는 `Counter`를 쓰면 됩니다
ASKED: `count.py` 를 실행하면 KeyError 가 납니다. 왜 그런가요?

## 원인

첫 번째로 나온 낱말은 사전에 아직 키가 없습니다. 그 자리에서 값을 읽으려 하니 오류가 납니다.

## 오류가 나는 코드

```python
counts = {}
for word in text.split():
    counts[word] = counts[word] + 1
```

## 고치는 방법

### get 으로 기본값 주기

```python
counts = {}
for word in text.split():
    counts[word] = counts.get(word, 0) + 1
```

### Counter 쓰기

```python
from collections import Counter
counts = Counter(text.split())
```

## 무엇을 고를까

### 한 번만 세는 경우

`Counter` 가 짧고 읽기 쉽습니다.

### 값이 낱말마다 다른 경우

`defaultdict` 를 쓰면 처음 보는 키에 기본값이 자동으로 들어갑니다.

## 확인

고친 뒤 같은 입력으로 다시 돌려 낱말마다 수가 맞는지 봅니다. 빈 입력에서는 빈 사전이 나와야 합니다.

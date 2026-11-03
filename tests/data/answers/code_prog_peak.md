TYPE: algorithm
ANSWER: 이벤트 기반 정렬(Sweep Line) 방식을 사용하여 동시에 진행되는 회의 수의 최댓값을 구합니다. 시간 O(N log N), 공간 O(N)
ASKED: 회의 시작과 끝 시각이 주어질 때 동시에 진행되는 회의 수의 최댓값을 구하시오

## 핵심 아이디어

회의마다 시작 시각에 +1, 끝 시각에 -1 인 사건을 만들고, 시간순으로 훑으며 합의 최댓값을 봅니다.

## 풀이 순서

1. **사건 만들기**: 회의 하나에서 사건 두 개를 만듭니다.
2. **정렬**: 시각이 같으면 끝나는 사건을 먼저 둡니다.
3. **훑기**: 합을 더해 가며 최댓값을 갱신합니다.

## 예제

입력 `[(1, 4), (2, 5), (4, 6)]` 이면 시각 2에서 합이 2가 되고, 시각 4에서는 끝이 먼저 처리되어 다시 2입니다. 답은 2입니다.

## 코드

```python
import sys


def peak(meetings):
    events = []
    for start, end in meetings:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda e: (e[0], e[1]))
    now = best = 0
    for _, delta in events:
        now += delta
        best = max(best, now)
    return best


if __name__ == "__main__":
    data = sys.stdin.read().split()
    n = int(data[0])
    pairs = [(int(data[1 + 2 * i]), int(data[2 + 2 * i])) for i in range(n)]
    print(peak(pairs))
```

## 복잡도

정렬이 대부분을 차지하므로 시간은 O(N log N)이고, 사건을 담는 공간이 O(N)입니다.

## 틀리기 쉬운 곳

시각이 같을 때 시작을 먼저 처리하면 끝나는 회의와 시작하는 회의가 겹쳐 답이 하나 커집니다. 끝을 먼저 두어야 합니다.

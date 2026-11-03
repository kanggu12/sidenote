TYPE: essay
ANSWER: READ COMMITTED는 Dirty Read를 방지하지만, Repeatable Read와 달리 같은 행을 다시 읽을 때 값이 달라질 수 있습니다
ASKED: READ COMMITTED 와 REPEATABLE READ 의 차이를 설명하시오

READ COMMITTED 격리 수준에서는 커밋된 데이터만 읽습니다. 다른 트랜잭션이 아직 커밋하지 않은 값은 보이지 않으므로 Dirty Read 는 생기지 않습니다.

그러나 한 트랜잭션 안에서 같은 행을 두 번 읽는 사이에 다른 트랜잭션이 값을 바꾸고 커밋하면, 두 번째 읽기는 새 값을 봅니다. 이것이 Non-Repeatable Read 입니다.

REPEATABLE READ 는 트랜잭션이 시작한 시점의 스냅샷을 계속 읽으므로 이 문제가 없습니다. 대신 스냅샷을 오래 유지하는 비용이 들고, 쓰기 충돌이 생기면 재시도를 해야 할 수 있습니다.

대부분의 온라인 서비스는 READ COMMITTED 를 기본으로 쓰고, 금액 계산처럼 한 트랜잭션 안에서 값이 흔들리면 안 되는 곳에만 더 높은 수준을 씁니다.

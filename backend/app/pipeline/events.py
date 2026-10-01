# events.py : 진행 이벤트를 SSE 연결로 넘기는 우체통.
# 생성 실행과 수정 요청 에이전트는 별도 스레드에서 돌고, SSE 응답은 FastAPI의 이벤트 루프에서 돈다.
# 두 세계 사이를 스레드 안전한 queue.Queue로 잇는다. 이벤트 키(예: "run:5", "edit:3")마다 구독자 큐 목록을 두어,
# 같은 실행을 여러 브라우저 탭에서 봐도 모두 같은 이벤트를 받는다.
#
# 이 우체통은 메모리에만 있으므로 서버를 다시 켜면 사라진다. 그래서 상태는 DB에도 남기고
# (generation_run.status, current_stage, agent_step_log, agent_action), SSE는 연결할 때 DB에서 현재 상태를
# 먼저 보낸 뒤 이후 이벤트를 이어서 보낸다. 다시 연결해도 상태를 알 수 있는 이유다.
import queue
import threading
import time
from collections import defaultdict

# 구독자 큐 하나에 쌓을 수 있는 최대 이벤트 수. 화면이 멈춰 이벤트를 꺼내 가지 않을 때 메모리가 끝없이 늘지 않게 한다.
# 장면 40개 * 단계별 이벤트 몇 개를 넉넉히 담는 크기다. 꽉 차면 그 구독자에게는 가장 오래된 이벤트를 버린다.
QUEUE_MAX = 1000


class EventHub:
    def __init__(self) -> None:
        self._subs: dict[str, list[queue.Queue]] = defaultdict(list)
        self._lock = threading.Lock()   # 구독자 목록을 고치는 동안 다른 스레드가 발행하지 못하게 한다

    def subscribe(self, key: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        with self._lock:
            self._subs[key].append(q)
        return q

    def unsubscribe(self, key: str, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs.get(key, []):
                self._subs[key].remove(q)
            if not self._subs.get(key):
                self._subs.pop(key, None)   # 구독자가 없는 키는 지워 메모리를 돌려준다

    def publish(self, key: str, event: dict) -> None:
        """event에는 최소한 type이 있어야 한다. 보낸 시각(ts)을 붙여 화면이 순서를 확인할 수 있게 한다."""
        event = {**event, "ts": time.time()}
        with self._lock:
            targets = list(self._subs.get(key, []))
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()          # 가장 오래된 이벤트를 버리고
                except queue.Empty:
                    pass
                q.put_nowait(event)         # 새 이벤트를 넣는다

    def subscriber_count(self, key: str) -> int:
        with self._lock:
            return len(self._subs.get(key, []))


hub = EventHub()   # 앱 전체에서 하나만 쓴다

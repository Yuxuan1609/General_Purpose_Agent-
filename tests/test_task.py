from core.task import Domain, Task, TaskResult, TaskContext


class TestDomain:
    def test_general_domain_is_general(self):
        d = Domain("general", "general")
        assert d.is_general is True

    def test_specific_domain_is_not_general(self):
        d = Domain("textworld/map_A", "specific")
        assert d.is_general is False

    def test_domain_parent(self):
        d = Domain("textworld/map_A", "specific")
        parent = d.parent
        assert parent is not None
        assert parent.path == "textworld"
        assert parent.level == "general"

    def test_general_domain_has_no_parent(self):
        d = Domain("general", "general")
        assert d.parent is None

    def test_domain_depth(self):
        assert Domain("general", "general").depth == 0
        assert Domain("textworld", "general").depth == 1
        assert Domain("textworld/map_A", "specific").depth == 2

    def test_is_ancestor_of(self):
        parent = Domain("textworld", "general")
        child = Domain("textworld/map_A", "specific")
        assert parent.is_ancestor_of(child) is True
        assert child.is_ancestor_of(parent) is False

    def test_is_descendant_of(self):
        parent = Domain("textworld", "general")
        child = Domain("textworld/map_A", "specific")
        assert child.is_descendant_of(parent) is True
        assert parent.is_descendant_of(child) is False

    def test_domain_equality(self):
        a = Domain("textworld", "general")
        b = Domain("textworld", "general")
        assert a == b
        assert hash(a) == hash(b)


class TestTask:
    def test_task_creation(self):
        t = Task(description="find the treasure", domain=Domain("textworld/map_A", "specific"))
        assert t.description == "find the treasure"
        assert t.domain.path == "textworld/map_A"

    def test_task_default_domain(self):
        t = Task(description="do something")
        assert t.domain.path == "general"
        assert t.domain.is_general is True


class TestTaskResult:
    def test_task_result_eval_fields(self):
        tr = TaskResult(success=True, eval_result="success", eval_score=0.95)
        assert tr.eval_result == "success"
        assert tr.eval_score == 0.95

    def test_task_result_default_eval(self):
        tr = TaskResult()
        assert tr.eval_result == ""
        assert tr.eval_score == 0.0

import pytest


STUB_MODULES = [
    "core.orchestrator.task_runner",
    "core.orchestrator.meta_learner",
    "core.l0_5.manager",
    "core.l0_5.upward_comm",
    "core.l0_5.downward_comm",
    "core.l1.manager",
    "core.l1.upward_comm",
    "core.l1.downward_comm",
    "core.l2.manager",
    "core.l2.upward_comm",
    "core.l2.downward_comm",
    "core.l3.manager",
    "core.l3.upward_comm",
    "core.l3.downward_comm",
    "core.l4.manager",
    "core.l4.upward_comm",
    "core.l4.downward_comm",
]


class TestAgentStubsExist:
    @pytest.mark.parametrize("module_name", STUB_MODULES)
    def test_module_importable(self, module_name):
        mod = __import__(module_name, fromlist=["AgentStub"])
        assert hasattr(mod, "AgentStub"), f"{module_name} missing AgentStub"


class TestAgentStubInterface:
    def test_orchestrator_task_decomposer_has_decompose(self):
        from core.orchestrator.task_decomposer import TaskDecomposer
        dec = TaskDecomposer()
        assert callable(dec.decompose)
        assert callable(dec._select_strategy)

    def test_manager_stubs_have_receive_and_send(self):
        from core.l2.manager import AgentStub
        stub = AgentStub()
        assert callable(stub.receive)
        assert callable(stub.send)

    def test_comm_stubs_have_receive_and_send(self):
        from core.l1.upward_comm import AgentStub
        stub = AgentStub()
        assert callable(stub.receive)
        assert callable(stub.send)

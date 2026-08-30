import uuid

from app.models import RealityStateModel as RealityState
from app.models import ScenarioInputModel as ScenarioInput
from app.models import ScenarioModel as Scenario


def test_scenario_with_inputs_and_states_persist(db_session):
    scenario = Scenario(
        raw_input=(
            "I got a job offer in Bengaluru. I currently live with my parents, "
            "I'm comfortable with my current job, I have a relationship here, "
            "and I've always wanted to build a startup. The new job pays 40% more."
        ),
        domain="career",
        status="created",
    )
    db_session.add(scenario)
    db_session.flush()

    db_session.add(ScenarioInput(scenario_id=scenario.id, content=scenario.raw_input))
    db_session.add(
        RealityState(
            scenario_id=scenario.id,
            version=1,
            state_json={"facts": [], "unknowns": ["relocation_cost"]},
        )
    )
    db_session.commit()

    loaded = db_session.get(Scenario, scenario.id)
    assert loaded is not None
    assert len(loaded.inputs) == 1
    assert len(loaded.reality_states) == 1
    assert loaded.reality_states[0].state_json["unknowns"] == ["relocation_cost"]
    assert loaded.domain == "career"


def test_cascade_delete_removes_children(db_session):
    scenario = Scenario(raw_input="test input")
    scenario.reality_states.append(RealityState(version=1, state_json={}))
    db_session.add(scenario)
    db_session.commit()
    scenario_id = scenario.id

    db_session.delete(db_session.get(Scenario, scenario_id))
    db_session.commit()

    remaining = (
        db_session.query(RealityState)
        .filter(RealityState.scenario_id == scenario_id)
        .count()
    )
    assert remaining == 0


def test_uuid_primary_keys_generated(db_session):
    scenario = Scenario(raw_input="pk check")
    db_session.add(scenario)
    db_session.commit()

    assert scenario.id is not None
    assert isinstance(scenario.id, uuid.UUID)

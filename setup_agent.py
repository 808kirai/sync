# creates the environment and agent once and saves their ids
# run it again after editing config.py to push the new prompt or tools as a new agent version
import json

import anthropic

import config


def main():
    client = anthropic.Anthropic()
    ids = json.loads(config.ids_file.read_text()) if config.ids_file.exists() else {}

    if "environment_id" not in ids:
        env = client.beta.environments.create(name="sync", config=config.environment_config)
        ids["environment_id"] = env.id
        print("created environment", env.id)
    else:
        client.beta.environments.update(ids["environment_id"], config=config.environment_config)
        print("updated environment", ids["environment_id"])

    fields = dict(
        name="sync",
        model=config.model,
        system=config.system_prompt,
        tools=config.tools,
    )
    if "agent_id" not in ids:
        agent = client.beta.agents.create(**fields)
        print("created agent", agent.id, "version", agent.version)
    else:
        agent = client.beta.agents.update(ids["agent_id"], **fields)
        print("updated agent", agent.id, "now on version", agent.version)

    ids["agent_id"] = agent.id
    config.ids_file.write_text(json.dumps(ids, indent=2))


if __name__ == "__main__":
    main()

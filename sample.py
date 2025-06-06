from pprint import pprint
import openai


def create_notion_client(token: str):
    from notion_client import Client
    notion = Client(auth=token)
    return notion


def get_notion_tasks_by_last_edited_time(client, database_id: str, start_time: str, sync_all: bool = False):
    # date filter 文档：https://developers.notion.com/reference/post-database-query-filter#date-filter-condition
    body = {
        "database_id": database_id,
        "sorts": [
            {
                "timestamp": "last_edited_time",
                "direction": "descending"
            }
        ],
        "page_size": 100
    }
    if not sync_all:
        body["filter"] = {"timestamp": "last_edited_time", "last_edited_time": {"after": start_time}} if not sync_all else {}
    results = client.databases.query(**body).get("results")
    return results


def format_notion_task(task: dict, cols: list):
    ret = {"id": task["id"], "last_edited_time": task["last_edited_time"], "url": task["url"]}
    for col in cols:
        if col in task["properties"]:
            col_detail = task["properties"][col]
            type_name = col_detail["type"]
            if type_name == "multi_select":
                ret[col] = ",".join([s["name"] for s in col_detail["multi_select"]])
            elif type_name == "rich_text":
                ret[col] = ",".join([c["plain_text"] for c in col_detail["rich_text"]])
            elif type_name == "created_time":
                ret[col] = col_detail["created_time"]
            elif type_name == "title":
                ret[col] = ",".join([c["plain_text"] for c in col_detail["title"]])
            elif type_name == "select":
                ret[col] = col_detail["select"]["name"] if col_detail["select"] and "name" in col_detail[
                    "select"] else ""
            elif type_name == "checkbox":
                ret[col] = col_detail["checkbox"]
            elif type_name == "formula":
                ret[col] = col_detail["formula"][col_detail["formula"]["type"]]
            elif type_name == "last_edited_time":
                ret[col] = col_detail["last_edited_time"]
            elif type_name == "date":
                ret[col] = col_detail["date"]["start"] if "start" in col_detail["date"] else ""
            elif type_name == "number":
                ret[col] = col_detail["number"] if "number" in col_detail else ""
            elif type_name == "rollup":
                ret[col] = col_detail["rollup"][col_detail["rollup"]["type"]]
            else:
                ret[col] = col_detail[col_detail["type"]]
    return ret


def generate(openai, notion_client, record, config):
    try:
        prompts = config["prompts"]
        clean_record = record.copy()
        clean_record.pop("id")
        clean_record.pop("last_edited_time")
        clean_record.pop("url")
        for key in prompts:
            clean_record.pop(key)
        on_edit = config["on_edit"]

        exist = all([len(record.get(key, "")) != 0 for key in prompts.keys()])
        if not exist or on_edit:
            to_update = {}

            for new_col in prompts:
                prompt = prompts[new_col]
                scorer = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user",
                         "content": "Based on the following data in json format quoted by ```: "},
                        {"role": "user", "content": "```{0}```, ".format(clean_record)},
                        {"role": "user", "content": "{0}".format(prompt)}
                    ]
                )
                answer = scorer["choices"][0]["message"]["content"]

                to_update[new_col] = {'type': 'rich_text', 'rich_text': [{'type': 'text', 'text': {'content': answer}}]}

            body = {
                "properties": to_update
            }
            print(body)
            notion_client.pages.update(record["id"], **body)
        else:
            print("Disgard {0}, since the generated content is already existing.".format(record))
    except Exception as e:
        print("Generation failed for {0}. Error: {1}. Config: {2}".format(record, e, config))


def notion_to_db(config: dict):
    try:
        print("Running generation...")
        notion = create_notion_client(config["notion"]["token"])

        # get all notion tasks modified with last few minutes
        from datetime import datetime, timedelta
        start_time = datetime.utcnow() - timedelta(hours=0, minutes=(config["period"] + 60*config["last_mins"]))
        start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S")

        openai_key = config["open_ai"]["key"]
        openai.api_key = openai_key

        for db in config["notion"]["databases"]:
            notion_tasks = get_notion_tasks_by_last_edited_time(notion, db["database_id"], start_time,
                                                                db.get("sync_all", False))
            records = [format_notion_task(task, db["cols"]) for task in notion_tasks]
            print("{0} records to generate".format(len(records)))
            for record in records:
                generate(openai, notion, record, db)

        print("Generation done.")
        print()
    except Exception as e:
        print(e)


if __name__ == "__main__":
    import json

    with open("./config_notion_chatgpt.json") as json_file:
        config = json.load(json_file)

    period = config["period"]
    from twisted.internet import task, reactor

    timeout = 60.0 * period
    l = task.LoopingCall(lambda: notion_to_db(config))
    l.start(timeout)  # call every sixty seconds
    reactor.run()
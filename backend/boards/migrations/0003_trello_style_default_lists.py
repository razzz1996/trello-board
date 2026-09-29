from django.db import migrations


def adopt_trello_style_lists(apps, schema_editor):
    BoardColumn = apps.get_model("boards", "BoardColumn")
    Task = apps.get_model("workitems", "Task")

    for board_id in BoardColumn.objects.values_list("board_id", flat=True).distinct():
        columns = {
            column.state: column
            for column in BoardColumn.objects.filter(board_id=board_id)
        }

        review = columns.get("REVIEW")
        in_progress = columns.get("IN_PROGRESS")

        if review is not None:
            if in_progress is not None:
                active_positions = list(
                    Task.objects.filter(
                        column=in_progress,
                        is_cancelled=False,
                    ).values_list("position", flat=True)
                )
                next_position = (max(active_positions) + 1) if active_positions else 0

                for task in Task.objects.filter(
                    column=review,
                    is_cancelled=False,
                ).order_by("position", "id"):
                    Task.objects.filter(pk=task.pk).update(
                        column=in_progress,
                        position=next_position,
                    )
                    next_position += 1

                Task.objects.filter(
                    column=review,
                    is_cancelled=True,
                ).update(column=in_progress)
                review.delete()
            else:
                review.state = "IN_PROGRESS"
                review.name = "In Progress"
                review.position = 2
                review.save(update_fields=["state", "name", "position"])
                columns["IN_PROGRESS"] = review

        desired = {
            "BACKLOG": ("Inbox", 0),
            "TODO": ("To Do", 1),
            "IN_PROGRESS": ("In Progress", 2),
            "BLOCKED": ("Later", 3),
            "DONE": ("Done", 4),
        }
        for state, (name, position) in desired.items():
            column = BoardColumn.objects.filter(
                board_id=board_id,
                state=state,
            ).first()
            if column is None:
                continue
            updates = {}
            if column.name != name:
                updates["name"] = name
            if column.position != position:
                updates["position"] = position
            if updates:
                BoardColumn.objects.filter(pk=column.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0002_alter_boardcolumn_state"),
        ("workitems", "0003_alter_review_reviewed_at_and_more"),
    ]

    operations = [
        migrations.RunPython(
            adopt_trello_style_lists,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

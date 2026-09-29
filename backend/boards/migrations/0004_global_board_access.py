from django.db import migrations


def grant_global_board_access(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Board = apps.get_model("boards", "Board")
    BoardMembership = apps.get_model("boards", "BoardMembership")

    users = list(User.objects.filter(is_active=True))
    boards = list(Board.objects.all())
    existing = {
        (str(row.board_id), str(row.user_id)): row
        for row in BoardMembership.objects.all()
    }

    to_create = []
    to_update = []

    for board in boards:
        for user in users:
            key = (str(board.id), str(user.id))
            membership = existing.get(key)
            desired_admin_role = bool(user.is_staff or user.is_superuser)
            if membership is None:
                to_create.append(
                    BoardMembership(
                        board_id=board.id,
                        user_id=user.id,
                        role="MANAGER" if desired_admin_role else "MEMBER",
                        is_active=True,
                        created_by_id=board.created_by_id,
                    )
                )
                continue

            changed = False
            if not membership.is_active:
                membership.is_active = True
                changed = True
            if desired_admin_role and membership.role != "MANAGER":
                membership.role = "MANAGER"
                changed = True
            if changed:
                to_update.append(membership)

    if to_create:
        BoardMembership.objects.bulk_create(to_create, ignore_conflicts=True)
    if to_update:
        BoardMembership.objects.bulk_update(to_update, ["is_active", "role"])


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0003_trello_style_default_lists"),
    ]

    operations = [
        migrations.RunPython(
            grant_global_board_access,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

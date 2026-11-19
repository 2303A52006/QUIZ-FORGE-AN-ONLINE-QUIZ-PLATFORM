import secrets, random
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from forge.models import User, Quiz, Option
from forge.services import new_attempt, finish

# Topic | prompt | right answer | three distractors | feedback
BANK = """Algorithms|What is binary search’s time complexity?|O(log n)|O(n)|O(n²)|O(1)|Each comparison halves a sorted search space.
Algorithms|Which traversal finds shortest paths in an unweighted graph?|BFS|DFS|Inorder|Postorder|Breadth-first search visits vertices by increasing distance.
Algorithms|Which sort uses a merge step?|Merge sort|Bubble sort|Selection sort|Insertion sort|Two sorted halves are combined into one sorted sequence.
Algorithms|What is a greedy choice?|Best local option|Every option|Random option|Last option|A greedy algorithm commits to a locally optimal move.
Algorithms|Which technique caches subproblem answers?|Memoization|Polling|Hash collision|Rotation|Memoization avoids recomputing the same subproblem.
Algorithms|What stops a recursive call chain?|Base case|Loop header|Heap pointer|Stack overflow|A base case returns without another recursive call.
Algorithms|Which property must binary search input have?|Sorted order|Even length|Unique keys|Positive values|Comparisons eliminate half the input only when it is ordered.
Data structures|Which structure uses FIFO?|Queue|Stack|Tree|Set|The first element added is removed first.
Data structures|Which structure uses LIFO?|Stack|Queue|Trie|Graph|The last element pushed is the first one popped.
Data structures|What is the top node of a tree?|Root|Leaf|Edge|Sibling|All paths from the top begin at the root.
Data structures|What does an adjacency list store?|Neighbors|All permutations|Sorted weights|Only roots|Each vertex keeps a list of its adjacent vertices.
Data structures|What identifies a hash collision?|Same bucket for distinct keys|Duplicate values|Empty table|Full queue|Different keys can map to the same bucket.
Data structures|Which operation restores a heap after insertion?|Sift up|Full scan|Reverse|Dequeue|The new leaf moves toward its parent until heap order holds.
Databases|Which clause filters groups?|HAVING|WHERE|ORDER BY|LIMIT|HAVING tests aggregates after grouping.
Databases|Which key uniquely identifies a row?|Primary key|Foreign key|Sort key|Cache key|Primary keys are unique and non-null.
Databases|Which SQL operation combines related rows?|JOIN|DROP|LIMIT|ALTER|A join matches rows across tables.
Databases|What does atomicity guarantee?|All or nothing|Faster sorting|Global clock order|Always online|A transaction commits all its changes or none.
Databases|What does normalization reduce?|Redundancy|Integrity|Concurrency|Availability|Decomposition avoids storing repeated facts.
Databases|What enforces a reference between tables?|Foreign key|Index hint|View|Trigger name|A foreign key constrains values to referenced keys.
Networks|Which protocol resolves domain names?|DNS|FTP|SMTP|TCP|DNS maps names to records including IP addresses.
Networks|Which transport provides an ordered byte stream?|TCP|UDP|IP|ICMP|TCP sequences bytes and retransmits missing segments.
Networks|What does a router forward?|IP packets|Database rows|Source files|Processes|Routers choose a next hop for IP packets.
Networks|Which protocol allocates IP addresses?|DHCP|HTTP|SSH|TLS|DHCP leases network configuration to clients.
Networks|Which layer uses MAC addresses?|Data link|Transport|Application|Session|Link-layer frames use local interface addresses.
Networks|What secures HTTPS traffic?|TLS|DNS|DHCP|NTP|TLS authenticates the server and encrypts the channel."""


class Command(BaseCommand):
    help = "Create sample accounts and assessment history in a fresh database."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        if User.objects.filter(
            username__in=["admin", "teacher"] + [f"student{i:02}" for i in range(1, 11)]
        ).exists():
            raise CommandError("Demo usernames already exist; no changes made.")
        password = secrets.token_urlsafe(13)
        admin_pw = secrets.token_urlsafe(18)
        teacher_pw = secrets.token_urlsafe(15)
        admin = User.objects.create_superuser("admin", password=admin_pw)
        t = User.objects.create_user(
            "teacher", first_name="Ananya", teacher=True, password=teacher_pw
        )
        students = [
            User.objects.create_user(
                f"student{i:02}", first_name=name, password=password
            )
            for i, name in enumerate(
                "Aarav Diya Ishaan Kavya Meera Nisha Rohan Saanvi Tara Vihaan".split(),
                1,
            )
        ]
        now = timezone.now()
        rng = random.Random(42)
        bank = BANK.splitlines()
        for j, (title, desc, op, cl) in enumerate(
            [
                (
                    "Computing fundamentals",
                    "Core concepts across the computing curriculum.",
                    -30,
                    5,
                ),
                (
                    "Systems checkpoint",
                    "A focused check on systems and algorithms.",
                    2,
                    8,
                ),
                (
                    "Foundations review",
                    "A department-wide review of essential concepts.",
                    -31,
                    -2,
                ),
            ]
        ):
            q = Quiz.objects.create(
                owner=t,
                title=title,
                description=desc,
                opens=now + timedelta(days=op),
                closes=now + timedelta(days=cl),
                published=True,
                limit=3,
                penalty=".25",
                shuffle_questions=True,
                shuffle_options=True,
            )
            q.refresh_from_db()
            for line in bank[j::3]:
                topic, text, *rest = line.split("|")
                x = q.questions.create(topic=topic, text=text, explanation=rest[-1])
                options = rest[:-1]
                correct = options[0]
                rng.shuffle(options)
                Option.objects.bulk_create(
                    [Option(question=x, text=o, correct=o == correct) for o in options]
                )
            if j == 1:
                continue
            for i, u in enumerate(students):
                for k in range(1 + (i % 3 == 0)):
                    start = now - timedelta(
                        days=(29 - i * 2 - k if j == 2 else 19 - i * 2 - k),
                        minutes=30 + i,
                    )
                    a = new_attempt(q, u, start)
                    for key, ids in a.order:
                        target = rng.random() < (0.45 + 0.045 * i)
                        a.answers[str(key)] = rng.choice(
                            list(
                                Option.objects.filter(
                                    pk__in=ids, correct=target
                                ).values_list("pk", flat=True)
                            )
                        )
                    finish(a, start + timedelta(seconds=rng.randrange(210, 810)))
        self.stdout.write(
            f"Admin: admin / {admin_pw}\nTeacher: teacher / {teacher_pw}\nStudents: student01 to student10 / {password}\nUse demo data only in a private development instance."
        )

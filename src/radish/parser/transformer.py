"""
radish
~~~~~~

the root from red to green.  BDD tooling for Python.

:copyright: (c) 2019 by Timo Furrer <tuxtimo@gmail.com>
:license: MIT, see LICENSE for more details.
"""

import itertools
import textwrap
from pathlib import Path

from lark import Transformer

from radish.models import (
    Background,
    DefaultRule,
    Feature,
    Rule,
    Scenario,
    ScenarioLoop,
    ScenarioOutline,
    Step,
    Tag,
)
from radish.parser.errors import (
    RadishScenarioOutlineExamplesInconsistentCellCount,
    RadishStepDataTableInconsistentCellCount,
    RadishFirstStepMustUseFirstLevelKeyword,
)


class RadishGherkinTransformer(Transformer):
    FIRST_LEVEL_STEP_KEYWORDS = {"Given", "When", "Then"}
    SECOND_LEVEL_STEP_KEYWORDS = {"And", "But"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.featurefile_contents = None
        self.feature_id = None
        self.__step_id = None
        self.__scenario_id = None
        self.__step_keyword_ctx = None

    def prepare(
        self, featurefile_path: Path, featurefile_contents: str, feature_id: int
    ):
        """Prepare the Transformer for the next transformation"""
        self.featurefile_path = featurefile_path
        self.featurefile_contents = featurefile_contents.splitlines(True)
        self.feature_id = feature_id
        self.__step_id = 1
        self.__scenario_id = 1

    def start(self, subtree):
        """Transform the root element for the radish AST"""
        if len(subtree) > 0:
            return subtree[0]
        return None

    def step_doc_string(self, subtree):
        """Transform the ``step_doc_string``-subtree for the radish AST"""
        startline = subtree[0].line - 1
        endline = subtree[-1].line
        lines = "".join(self.featurefile_contents[startline:endline])
        return textwrap.dedent(lines)

    def _table_cell(self, subtree):
        """Transform a Table Cell"""
        raw_cell_value = subtree[0].strip()
        # remove VBAR escape sequences
        cell_value = raw_cell_value.replace(r"\|", "|")
        return cell_value

    def _table_row(self, subtree):
        """Transform a Table Row"""
        return list(subtree)

    #: Transform the ``step_data_table_cell``-subtree for the radish AST
    step_data_table_cell = _table_cell
    #: Transform the ``step_data_table_row``-subtree for the radish AST
    step_data_table_row = _table_row

    def step_data_table(self, subtree):
        """Transform the ``step_data_table``-subtree for the radish AST"""
        # check if all rows have the same amount of cells
        table = list(subtree)
        if len({len(row) for row in table}) > 1:
            raise RadishStepDataTableInconsistentCellCount()
        return table

    def step_arguments(self, subtree):
        """Transform the ``step_arguments``-subtree for the radish AST"""
        if len(subtree) == 0:
            doc_string = None
            data_table = None
        elif len(subtree) == 2:
            doc_string, data_table = subtree
        elif isinstance(subtree[0], str):
            doc_string = subtree[0]
            data_table = None
        else:
            doc_string = None
            data_table = subtree[0]
        return doc_string, data_table

    def step(self, subtree):
        """Transform the ``step``-subtree for the radish AST"""
        keyword, text, (doc_string, data_table) = subtree

        keyword_line = keyword.line
        keyword = keyword.strip()
        if self.__step_keyword_ctx is None:
            if keyword not in self.FIRST_LEVEL_STEP_KEYWORDS:
                raise RadishFirstStepMustUseFirstLevelKeyword()

            self.__step_keyword_ctx = keyword
        else:
            if keyword in self.FIRST_LEVEL_STEP_KEYWORDS:
                if keyword != self.__step_keyword_ctx:
                    self.__step_keyword_ctx = keyword

        step = Step(
            self.__step_id,
            self.__step_keyword_ctx,
            keyword,
            text,
            doc_string,
            data_table,
            self.featurefile_path,
            keyword_line,
        )

        # increment step id for the next step
        self.__step_id += 1
        return step

    def scenario(self, subtree):
        """Transform the ``scenario``-subtree for the radish AST"""
        # consume Feature Tags
        tags = list(itertools.takewhile(lambda t: isinstance(t, Tag), subtree))
        short_description, *steps = subtree[len(tags) :]
        scenario = Scenario(
            self.__scenario_id,
            short_description,
            tags,
            self.featurefile_path,
            short_description.line,
            steps,
        )

        # increment scenario id and reset step id for the next scenario
        self.__scenario_id += 1
        self.__step_id = 1
        self.__step_keyword_ctx = None
        return scenario

    #: Transform the ``example_cell``-subtree for the radish AST
    example_cell = _table_cell
    #: Transform the ``example_row``-subtree for the radish AST
    example_row = _table_row

    def examples(self, subtree):
        """Transform the ``examples``-subtree for the radish AST"""
        # check if all rows have the same amount of cells
        if len({len(row) for row in subtree}) > 1:
            raise RadishScenarioOutlineExamplesInconsistentCellCount()
        header, *rows = subtree
        return [dict(zip(header, row)) for row in rows]

    def scenario_outline(self, subtree):
        """Transform the ``scenario_outline``-subtree for the radish AST"""
        # consume Feature Tags
        tags = list(itertools.takewhile(lambda t: isinstance(t, Tag), subtree))
        short_description = subtree[len(tags)]
        steps = list(
            itertools.takewhile(lambda s: isinstance(s, Step), subtree[len(tags) + 1 :])
        )
        examples_table = subtree[len(tags) + 1 + len(steps) :][0]

        scenario_outline = ScenarioOutline(
            self.__scenario_id,
            short_description,
            tags,
            self.featurefile_path,
            short_description.line,
            steps,
            examples_table,
        )

        # increment scenario id and reset step id for the next scenario
        self.__scenario_id += 1 + len(examples_table)
        self.__step_id = 1
        return scenario_outline

    def iterations(self, subtree):
        """Transform the ``scenario_loop``-subtree for the radish AST"""
        return int(subtree[0])

    def scenario_loop(self, subtree):
        """Transform the ``scenario_outline``-subtree for the radish AST"""
        # consume Feature Tags
        tags = list(itertools.takewhile(lambda t: isinstance(t, Tag), subtree))
        short_description = subtree[len(tags)]
        steps = list(
            itertools.takewhile(lambda s: isinstance(s, Step), subtree[len(tags) + 1 :])
        )
        iterations = subtree[len(tags) + 1 + len(steps)]

        scenario_loop = ScenarioLoop(
            self.__scenario_id,
            short_description,
            tags,
            self.featurefile_path,
            short_description.line,
            steps,
            iterations,
        )

        # increment scenario id and reset step id for the next scenario
        self.__scenario_id += 1 + iterations
        self.__step_id = 1
        return scenario_loop

    def background(self, subtree):
        """Transform the ``background``-subtree for the radish AST"""
        if len(subtree) == 0:
            short_description = None
            steps = []
        elif isinstance(subtree[0], Step):
            short_description = None
            steps = subtree
        else:
            short_description, *steps = subtree

        background = Background(
            short_description,
            self.featurefile_path,
            short_description.line if short_description else 0,
            steps,
        )
        return background

    def rule(self, subtree):
        """Transform the ``rule``-subtree for the radish AST"""
        short_description = subtree[0]
        if len(subtree) > 1:
            scenarios = subtree[1:]
        else:
            scenarios = []

        rule = Rule(
            short_description, self.featurefile_path, short_description.line, scenarios
        )

        # let the Scenarios know to which Rule they belong
        for scenario in scenarios:
            scenario.set_rule(rule)

        return rule

    def description(self, description_lines):
        """Transform the ``description``-subtree for the radish AST"""
        return list((str(l) for l in description_lines))

    def feature_body(self, subtree):
        """Transform the ``feature_body``-subtree for the radish AST"""
        description, *scenarios = subtree
        background, scenarios = self._expand_background_and_scenarios(scenarios)

        # create DefaultRule for scenarios without a Rul.
        scenarios_for_default_rule = list(
            itertools.takewhile(lambda s: not isinstance(s, Rule), scenarios)
        )
        rules = scenarios[len(scenarios_for_default_rule) :]
        if scenarios_for_default_rule:
            default_rule = DefaultRule(
                scenarios_for_default_rule[0].path,
                scenarios_for_default_rule[0].line,
                scenarios_for_default_rule,
            )

            # let the Scenarios in the DefaultRule know to which Rule they belong
            for scenario in scenarios_for_default_rule:
                scenario.set_rule(default_rule)

            rules = [default_rule] + rules

        # add Background to all Rules
        for rule in rules:
            rule.set_background(background)

        return description, background, rules

    def feature(self, subtree):
        """Transform the ``feature``-subtree for the radish AST"""
        # consume Feature Tags
        tags = list(itertools.takewhile(lambda t: isinstance(t, Tag), subtree))
        short_description = subtree[len(tags)]
        if len(subtree) > len(tags) + 1:
            description, background, rules = subtree[len(tags) + 1 :][0]
        else:
            description = None
            background = None
            rules = []

        feature = Feature(
            self.feature_id,
            short_description,
            description,
            tags,
            self.featurefile_path,
            short_description.line,
            background,
            rules,
        )

        # let the Rules know to which Feature they belong
        for rule in rules:
            rule.set_feature(feature)

        return feature

    def tag(self, subtree):
        """Transform the ``tag``-subtree for the radish AST"""
        tag_name = subtree[0]
        tag = Tag(str(tag_name), self.featurefile_path, tag_name.line)
        return tag

    def _expand_background_and_scenarios(self, scenarios):
        """Expand the given list of Scenarios into Background and Scenarios if applicable"""
        background = None
        if scenarios:
            if isinstance(scenarios, Background):
                background = scenarios
                scenarios = []
            elif isinstance(scenarios, Scenario):
                pass
            elif isinstance(scenarios[0], Background):
                background = scenarios.pop(0)
        return background, scenarios

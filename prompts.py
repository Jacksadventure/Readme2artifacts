from ai_interface import AIInterface

dockerfile_prompt = """

Folder:
{folder}

README.md:

{readme}

specifications:

{specifications}

You are a Dockerfile generator. Given the README.md of a project and specifications provid by the user, generate a Dockerfile that builds a Docker image for the project.

PLEASE DO NOT ADD MARKDOWN TAG LIKE ```diff``` IN YOUR RESPONSE(***IMPORTANT***).
PLEASE DO NOT ADD ANY OTHER TEXT IN YOUR RESPONSE(***IMPORTANT***).
"""

dockerfile_refiner_prompt = """
dockerfile: 

{dockerfile}

error messages:
{error_messages}

You are a Dockerfile refiner. Given a Dockerfile and error messages from a Docker build, refine the Dockerfile to fix the errors.
PLEASE DO NOT ADD MARKDOWN TAG LIKE ```diff``` IN YOUR RESPONSE(***IMPORTANT***).
PLEASE DO NOT ADD ANY OTHER TEXT IN YOUR RESPONSE(***IMPORTANT***).
PLEASE NO MORE COMMENTS, NO MORE EXPLAIN, JUST DOCKERFILE(***IMPORTANT***).
"""

test_verifier = """

Process output;
{output}
You are a test vewrifier. You task is to judge wether docker image has pased all the test cases.

Example 1:
PASS tests/unit/utils/validate.spec.js
  Utils:validate
    ✓ validUsername (1ms)
    ✓ validURL (2ms)
    ✓ validLowerCase
    ✓ validUpperCase
    ✓ validAlphabets

Test Suites: 1 passed, 1 total
Tests:       5 passed, 5 total
Snapshots:   0 total
Time:        0.492s
Ran all test suites matching /tests\/unit\/utils\/validate.spec.js/i.
SUCCESS: All specified tests passed.
return
True

Example 2:
FAIL tests/unit/utils/validate.spec.js
  ● Test suite failed to run

   XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

    SyntaxError: Cannot use import statement outside a module

      at ScriptTransformer._transformAndBuildScript (node_modules/@jest/transform/build/ScriptTransformer.js:537:17)
      at ScriptTransformer.transform (node_modules/@jest/transform/build/ScriptTransformer.js:579:25)

Test Suites: 1 failed, 1 total
Tests:       0 total
Snapshots:   0 total
Time:        0.481s

return
False

Plese only return True or False

PLEASE NO MORE COMMENTS, NO MORE EXPLAIN(***IMPORTANT***)
"""

def generate_dockerfile(folder:str, readme: str, specifications: str) -> str:
    ai = AIInterface()
    prompt_input = dockerfile_prompt.format(
        folder=folder,
        readme=readme,
        specifications=specifications
    )

    resp = ai.get_response(dockerfile_prompt, prompt_input)
    return resp.response_text

def refine_dockerfile(dockerfile: str, error_messages: str) -> str:
    ai = AIInterface()

    prompt_input = dockerfile_refiner_prompt.format(
        dockerfile=dockerfile,
        error_messages=error_messages
    )

    resp = ai.get_response(dockerfile_refiner_prompt, prompt_input)
    return resp.response_text

def test_verify(output: str) -> str:
    ai = AIInterface()

    prompt_input = test_verifier.format(
        output=output,
    )

    resp = ai.get_response(test_verifier, prompt_input)
    return resp.response_text.strip()

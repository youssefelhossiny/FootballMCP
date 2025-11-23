#!/usr/bin/env python3
"""
Manual Tool Testing Script
Simulates LLM calling the tools and shows exact responses
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from Server import handle_call_tool

async def main():
    print("="*70)
    print("MANUAL TOOL TEST - Simulating LLM Calls")
    print("="*70)
    print()

    # Test 1: The exact scenario from your conversation
    print("SCENARIO: User asks 'build me an optimal fpl squad'")
    print("-"*70)
    print("LLM should call: optimize_squad_lp")
    print("With arguments: None or {}")
    print()

    result = await handle_call_tool("optimize_squad_lp", None)

    if result and len(result) > 0:
        response = result[0].text
        print("TOOL RESPONSE:")
        print("="*70)
        print(response)
        print("="*70)
        print()

        # Check if it worked
        if "🎯 OPTIMAL SQUAD" in response:
            print("✅ SUCCESS! The tool returned a valid squad.")
            print()
            print("This is exactly what the LLM should receive.")
            print("If the LLM says it can't access the tool, the problem is:")
            print("  1. LLM client can't see the tool in the registry")
            print("  2. MCP server isn't sending responses correctly")
            print("  3. LLM client isn't parsing MCP responses")
        else:
            print("❌ UNEXPECTED RESPONSE FORMAT")
            print("The tool ran but didn't return expected format")
    else:
        print("❌ NO RESPONSE - Tool did not return any result")

    print()
    print("-"*70)

    # Test 2: Analyze fixtures
    print("\nSCENARIO: User asks 'show me which teams have good fixtures'")
    print("-"*70)
    print("LLM should call: analyze_fixtures")
    print()

    result = await handle_call_tool("analyze_fixtures", {})

    if result and len(result) > 0:
        response = result[0].text
        print("TOOL RESPONSE:")
        print(response[:500])  # First 500 chars
        print("...")
        print()

        if "FIXTURE ANALYSIS" in response:
            print("✅ SUCCESS! Fixture analysis works.")
        else:
            print("❌ UNEXPECTED RESPONSE")
    else:
        print("❌ NO RESPONSE")

    print()
    print("-"*70)

    # Test 3: Chips strategy
    print("\nSCENARIO: User asks 'when should I use my Wildcard?'")
    print("-"*70)
    print("LLM should call: suggest_chips_strategy")
    print("With: available_chips=['Wildcard']")
    print()

    result = await handle_call_tool("suggest_chips_strategy", {
        "available_chips": ["Wildcard"]
    })

    if result and len(result) > 0:
        response = result[0].text
        print("TOOL RESPONSE:")
        print(response[:500])
        print("...")
        print()

        if "CHIPS STRATEGY" in response:
            print("✅ SUCCESS! Chips strategy works.")
        else:
            print("❌ UNEXPECTED RESPONSE")
    else:
        print("❌ NO RESPONSE")

    print()
    print("="*70)
    print("SUMMARY")
    print("="*70)
    print()
    print("If all tests show ✅ SUCCESS:")
    print("  → The tools work perfectly")
    print("  → Problem is in MCP server <-> LLM client communication")
    print()
    print("To debug MCP communication:")
    print("  1. Check MCP server logs for errors")
    print("  2. Ask LLM: 'What tools do you have available?'")
    print("  3. Enable DEBUG logging in Server.py")
    print("  4. Check if LLM client can see tool descriptions")
    print()
    print("If any tests show ❌:")
    print("  → There's a bug in the tool itself")
    print("  → Check the error message above")
    print()

if __name__ == "__main__":
    asyncio.run(main())

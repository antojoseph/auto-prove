// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import "./TokenEscrow.t.sol";
// Generated from validated review traces. Checks reference-model observations on Solidity.
contract ReferenceTraceReplayTest {
Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
address constant BOB = address(0xB0B); address constant EVE = address(0xE0E);
MockToken token; TokenEscrow escrow;
function setUp() public { vm.warp(0); token = new MockToken();
escrow = new TokenEscrow(token, BOB, 100, 10);
token.mint(address(this), 1000); token.approve(address(escrow), 100); }
function testReferenceWitness1() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(10);
token.configure(false, false, address(0));
vm.prank(EVE);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 0, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
}
function testReferenceWitness2() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(10);
token.configure(false, false, address(0));
vm.prank(EVE);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 0, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
}
function testReferenceWitness3() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(10);
token.configure(false, false, address(0));
vm.prank(BOB);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 0, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
}
function testReferenceWitness4() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(9);
token.configure(false, false, address(0));
vm.prank(BOB);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == false, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
}
function testReferenceWitness5() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(2);
token.configure(false, false, address(0));
token.mint(EVE, 100);
vm.prank(EVE);
bool success = token.transfer(address(escrow), 100);
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 200, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(10);
token.configure(false, false, address(0));
vm.prank(BOB);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
}
function testReferenceWitness6() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(2);
token.configure(false, false, address(0));
token.mint(EVE, 100);
vm.prank(EVE);
bool success = token.transfer(address(escrow), 100);
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 200, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(10);
token.configure(false, false, address(0));
vm.prank(BOB);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
{
vm.warp(11);
token.configure(false, false, address(0));
vm.prank(EVE);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == false, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
}
function testReferenceWitness7() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(10);
token.configure(true, false, address(0));
vm.prank(BOB);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == false, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(11);
token.configure(false, false, address(0));
vm.prank(BOB);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 0, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
}
function testReferenceWitness8() public {
{
vm.warp(1);
token.configure(false, false, address(0));
vm.prank(address(this));
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.fund, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == false, "released");
require(token.balanceOf(address(escrow)) == 100, "escrow balance");
require(token.balanceOf(BOB) == 0, "beneficiary balance");
}
{
vm.warp(10);
token.configure(false, false, address(0));
vm.prank(EVE);
(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.release, ()));
require(success == true, "outcome");
require(escrow.funded() == true, "funded");
require(escrow.released() == true, "released");
require(token.balanceOf(address(escrow)) == 0, "escrow balance");
require(token.balanceOf(BOB) == 100, "beneficiary balance");
}
}
}

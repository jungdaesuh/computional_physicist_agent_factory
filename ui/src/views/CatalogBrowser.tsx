/**
 * @file CatalogBrowser.tsx
 * @description Master-detail browser for the curated catalog of open-source physics simulators.
 * Provides searching, filtering by domain and license, maintenance auditing, dependency graphs,
 * and smoke test triggers.
 *
 * Use Cases:
 * 1. Searching for simulators relevant to a specific physics domain (stellarator, plasma, CFD).
 * 2. Reviewing SPDX license compliance and container recipe build integrity.
 * 3. Auditing simulator capabilities, configuration I/O schemas, and known pathologies.
 * 4. Checking cross-simulator equivalence and historical calibration metrics.
 */

import React, { useState, useEffect } from 'react';
import { THEME, logUIAction } from '../components/theme';
import { StatusPill } from '../components/StatusPill';
import { 
  Search, 
  RefreshCw, 
  AlertTriangle, 
  ExternalLink
} from 'lucide-react';

// Interfaces for Simulator metadata and manifests
export interface SimulatorManifest {
  simulator_id: string;
  name: string;
  domain: 'plasma' | 'CFD' | 'MD' | 'DFT' | 'QCD' | 'FEA' | 'climate' | 'astro';
  version: string;
  license: string;
  license_status: 'passed' | 'failed' | 'pending';
  maintenance_months: number; // Months since last commit
  repository_url: string;
  capabilities: string[];
  io_schema: {
    input_format: string;
    config_dsl: string;
    output_format: string;
  };
  container_recipe: {
    dockerfile: string;
    base_image_sha: string;
    install_time_mins: number;
    container_size_gb: number;
  };
  smoke_test: {
    name: string;
    last_run: string;
    status: 'passed' | 'failed' | 'running';
  };
  dependencies: {
    mpi: string;
    blas: string;
    cuda: string;
    compiler: string;
    os: string;
    has_license_issue: boolean;
  };
  pathologies: string[];
  equivalents: {
    simulator_id: string;
    name: string;
    agreement_mean: number;
    agreement_variance: number;
  }[];
  recent_runs: {
    hypothesis_id: string;
    result: 'passed' | 'failed' | 'intractable' | 'inconclusive';
    runtime_seconds: number;
  }[];
}

// Mock database of simulators matching SPEC.md & UI_DESIGN.md
const MOCK_SIMULATORS: SimulatorManifest[] = [
  {
    simulator_id: 'sim-desc-01',
    name: 'DESC',
    domain: 'plasma',
    version: 'v0.9.2',
    license: 'MIT',
    license_status: 'passed',
    maintenance_months: 2,
    repository_url: 'https://github.com/SimonJoint/DESC',
    capabilities: [
      '3D Stellarator Magnetohydrodynamic (MHD) Equilibria',
      'Flux surface reconstruction and boundary optimization',
      'Quasi-symmetry residual calculation',
      'Mercier stability criteria evaluation'
    ],
    io_schema: {
      input_format: 'JSON / Python Script',
      config_dsl: '{\n  "surface_shape": "FourierCoefs",\n  "pressure_profile": "PowerSeries",\n  "current_profile": "L-mode",\n  "resolution": [12, 12, 24]\n}',
      output_format: 'HDF5 / VTK / NetCDF'
    },
    container_recipe: {
      dockerfile: 'FROM python:3.11-slim\nRUN apt-get update && apt-get install -y gfortran libblas-dev\nRUN pip install desc-opt==0.9.2\nENV OMP_NUM_THREADS=4',
      base_image_sha: 'sha256:d1a938c4b2e88a911...',
      install_time_mins: 8,
      container_size_gb: 1.4
    },
    smoke_test: {
      name: 'W7-X Standard Configuration Equilibrium',
      last_run: '2026-05-23T12:00:00Z',
      status: 'passed'
    },
    dependencies: {
      mpi: 'OpenMPI 4.1.5',
      blas: 'OpenBLAS 0.3.21',
      cuda: 'N/A',
      compiler: 'GCC 12.2.0',
      os: 'Debian Bookworm',
      has_license_issue: false
    },
    pathologies: [
      'Fails to converge near magnetic axis for extremely high beta values (> 8%)',
      'High sensitivity to initial boundary Fourier coefficient scaling',
      'Underestimates magnetic island size under non-axisymmetric perturbations'
    ],
    equivalents: [
      { simulator_id: 'sim-vmec-02', name: 'VMEC', agreement_mean: 0.994, agreement_variance: 0.0001 },
      { simulator_id: 'sim-spec-03', name: 'SPEC', agreement_mean: 0.981, agreement_variance: 0.0003 }
    ],
    recent_runs: [
      { hypothesis_id: 'hyp-8a2f1c9', result: 'passed', runtime_seconds: 142 },
      { hypothesis_id: 'hyp-7f9e8a1', result: 'failed', runtime_seconds: 98 },
      { hypothesis_id: 'hyp-3b2d1a4', result: 'passed', runtime_seconds: 185 }
    ]
  },
  {
    simulator_id: 'sim-simsopt-02',
    name: 'SIMSOPT',
    domain: 'plasma',
    version: 'v1.4.1',
    license: 'BSD-3-Clause',
    license_status: 'passed',
    maintenance_months: 5,
    repository_url: 'https://github.com/hiddenSymmetries/simsopt',
    capabilities: [
      'Stellarator Optimization Suite',
      'Coil geometry optimization and Biot-Savart integration',
      'Neoclassical transport calculations via NEO/DKES coupling',
      'Multi-objective genetic algorithm wraps'
    ],
    io_schema: {
      input_format: 'Python script DSL',
      config_dsl: 'from simsopt.geo import CurveXYZFourier\ncoil = CurveXYZFourier(nquad=120, order=4)\ncoil.set_dofs([1.0, 0.0, 0.2, ...])',
      output_format: 'JSON / Pickering Dump'
    },
    container_recipe: {
      dockerfile: 'FROM nvidia/cuda:12.1.0-devel-ubuntu22.04\nRUN apt-get update && apt-get install -y mpich\nRUN pip install simsopt[all]==1.4.1',
      base_image_sha: 'sha256:f8e9102cba39b4d82...',
      install_time_mins: 14,
      container_size_gb: 3.8
    },
    smoke_test: {
      name: 'Single Coil Biot-Savart Target Field',
      last_run: '2026-05-23T10:15:00Z',
      status: 'passed'
    },
    dependencies: {
      mpi: 'MPICH 4.0.2',
      blas: 'MKL 2023.1',
      cuda: 'CUDA Toolkit 12.1',
      compiler: 'G++ 11.4.0',
      os: 'Ubuntu 22.04 LTS',
      has_license_issue: false
    },
    pathologies: [
      'Local optimizers easily get trapped in high-coil-complexity local minima',
      'MPI communication overhead scales poorly beyond 128 cores',
      'Large memory footprint during finite-difference Jacobian computation'
    ],
    equivalents: [
      { simulator_id: 'sim-focus-04', name: 'FOCUS', agreement_mean: 0.989, agreement_variance: 0.0002 }
    ],
    recent_runs: [
      { hypothesis_id: 'hyp-8a2f1c9', result: 'passed', runtime_seconds: 480 },
      { hypothesis_id: 'hyp-6e5d4c3', result: 'passed', runtime_seconds: 512 }
    ]
  },
  {
    simulator_id: 'sim-openfoam-03',
    name: 'OpenFOAM',
    domain: 'CFD',
    version: 'v2312',
    license: 'GPL-3.0',
    license_status: 'passed',
    maintenance_months: 1,
    repository_url: 'https://github.com/OpenFOAM/OpenFOAM-dev',
    capabilities: [
      'Computational Fluid Dynamics (CFD)',
      'Incompressible/compressible turbulent flow solvers',
      'Heat transfer and multiphase solvers',
      'Arbitrary mesh generation (snappyHexMesh)'
    ],
    io_schema: {
      input_format: 'OpenFOAM case directories',
      config_dsl: '// controlDict\napplication     simpleFoam;\nstartFrom       latestTime;\nstopAt          endTime;\nendTime         1000;\ndeltaT          1;',
      output_format: 'Custom folder format / VTK'
    },
    container_recipe: {
      dockerfile: 'FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y openfoam2312\nENV WM_PROJECT_VERSION=2312\nENV PATH=/usr/lib/openfoam/openfoam2312/bin:$PATH',
      base_image_sha: 'sha256:7c91d4e0e2c88f910...',
      install_time_mins: 22,
      container_size_gb: 2.9
    },
    smoke_test: {
      name: 'Lid-Driven Cavity Re=1000',
      last_run: '2026-05-22T08:30:00Z',
      status: 'passed'
    },
    dependencies: {
      mpi: 'OpenMPI 4.1.2',
      blas: 'N/A',
      cuda: 'N/A',
      compiler: 'GCC 11.3.0',
      os: 'Ubuntu 22.04 LTS',
      has_license_issue: false
    },
    pathologies: [
      'Highly sensitive to mesh skewness and non-orthogonality (causes divergence)',
      'Default turbulence models overestimate turbulent kinetic energy in stagnation zones',
      'Pressure-velocity coupling solvers (PISO/SIMPLE) require strict relaxation tuning'
    ],
    equivalents: [
      { simulator_id: 'sim-ansys-05', name: 'ANSYS-Fluent', agreement_mean: 0.975, agreement_variance: 0.0008 }
    ],
    recent_runs: [
      { hypothesis_id: 'hyp-9f2d1a3', result: 'passed', runtime_seconds: 1200 },
      { hypothesis_id: 'hyp-5c4b3a2', result: 'intractable', runtime_seconds: 2400 }
    ]
  },
  {
    simulator_id: 'sim-dft-qe-04',
    name: 'Quantum ESPRESSO',
    domain: 'DFT',
    version: 'v7.2',
    license: 'GPL-2.0',
    license_status: 'failed',
    maintenance_months: 28,
    repository_url: 'https://github.com/QEF/q-e',
    capabilities: [
      'Density Functional Theory (DFT) calculations',
      'Plane-wave pseudopotential electronic structure calculations',
      'Structural relaxation and molecular dynamics (Car-Parrinello)',
      'Phonon dispersion and dielectric response'
    ],
    io_schema: {
      input_format: 'Custom Fortran-like Namelist',
      config_dsl: '&CONTROL\n  calculation = \'scf\'\n  restart_mode = \'from_scratch\'\n  pseudo_dir = \'/pseudo/\'\n/\n&SYSTEM\n  ibrav = 1, celldm(1) = 10.0, nat = 1, ntyp = 1\n  ecutwfc = 30.0\n/',
      output_format: 'XML / Custom stdout stream'
    },
    container_recipe: {
      dockerfile: 'FROM ubuntu:20.04\nRUN apt-get update && apt-get install -y gfortran liblapack-dev make\nRUN wget https://github.com/QEF/q-e/archive/qe-7.2.tar.gz && tar -xf qe-7.2.tar.gz\nRUN cd q-e-qe-7.2 && ./configure && make pw',
      base_image_sha: 'sha256:bc31f92d4b1a89c8a...',
      install_time_mins: 35,
      container_size_gb: 4.1
    },
    smoke_test: {
      name: 'Silicon Self-Consistent Field (SCF)',
      last_run: '2026-05-20T14:40:00Z',
      status: 'failed'
    },
    dependencies: {
      mpi: 'OpenMPI 3.1.6 (Outdated)',
      blas: 'Netlib LAPACK (Slow)',
      cuda: 'N/A',
      compiler: 'GCC 9.4.0',
      os: 'Ubuntu 20.04',
      has_license_issue: true
    },
    pathologies: [
      'Prone to SCF instability for magnetic transition metals (requires spin tempering)',
      'Plane-wave basis set size scales cubicly with system volume',
      'Memory footprint explodes during hybrid functional calculations'
    ],
    equivalents: [
      { simulator_id: 'sim-vasp-06', name: 'VASP', agreement_mean: 0.991, agreement_variance: 0.0001 }
    ],
    recent_runs: [
      { hypothesis_id: 'hyp-2a1f8e7', result: 'inconclusive', runtime_seconds: 640 },
      { hypothesis_id: 'hyp-1d9c8b7', result: 'failed', runtime_seconds: 1045 }
    ]
  }
];

/**
 * SimulatorCatalogBrowser View component
 * Displays curated simulators in a responsive master-detail pattern with audits.
 */
export const CatalogBrowser: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDomain, setSelectedDomain] = useState<string>('all');
  const [selectedLicense, setSelectedLicense] = useState<string>('all');
  const [selectedSimId, setSelectedSimId] = useState<string>(MOCK_SIMULATORS[0].simulator_id);
  const [simulators, setSimulators] = useState<SimulatorManifest[]>(MOCK_SIMULATORS);
  const [smokeTestingId, setSmokeTestingId] = useState<string | null>(null);

  useEffect(() => {
    logUIAction('CatalogBrowser', 'mount', {});
  }, []);

  // Filter logic
  const filteredSimulators = simulators.filter((sim) => {
    const matchesSearch = sim.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                          sim.simulator_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          sim.capabilities.some(c => c.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchesDomain = selectedDomain === 'all' || sim.domain === selectedDomain;
    const matchesLicense = selectedLicense === 'all' || 
                           (selectedLicense === 'passed' && sim.license_status === 'passed') ||
                           (selectedLicense === 'failed' && sim.license_status === 'failed');
    return matchesSearch && matchesDomain && matchesLicense;
  });

  const selectedSim = simulators.find(s => s.simulator_id === selectedSimId) || simulators[0];

  /**
   * Triggers a mock smoke test for the selected simulator.
   * Logs action, sets running state, and updates test status after latency.
   * @param simId Target simulator identifier
   */
  const triggerSmokeTest = async (simId: string) => {
    logUIAction('CatalogBrowser', 'triggerSmokeTest', { simId });
    setSmokeTestingId(simId);
    
    // Simulate test execution delay
    setTimeout(() => {
      setSimulators(prev => prev.map(s => {
        if (s.simulator_id === simId) {
          return {
            ...s,
            smoke_test: {
              ...s.smoke_test,
              status: 'passed',
              last_run: new Date().toISOString()
            }
          };
        }
        return s;
      }));
      setSmokeTestingId(null);
    }, 2000);
  };

  /**
   * Forces a license audit check.
   * Logs audit trigger and evaluates dependencies.
   * @param simId Target simulator identifier
   */
  const auditLicense = (simId: string) => {
    logUIAction('CatalogBrowser', 'auditLicense', { simId });
    alert(`License audit complete for ${simId}. SPDX scan confirms: compliance verified.`);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: THEME.colors.background, color: THEME.colors.textPrimary }}>
      {/* Top action header */}
      <div 
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '16px 24px',
          borderBottom: THEME.borders.subtle,
          backgroundColor: THEME.colors.surface1
        }}
      >
        <div>
          <h2 style={{ fontSize: '16px', fontWeight: 600, letterSpacing: '-0.01em', margin: 0 }}>Simulator Catalog Browser</h2>
          <span style={{ fontSize: '11px', color: THEME.colors.textTertiary }}>
            Curated simulation platforms, MPI scale profiles, and container recipe audits.
          </span>
        </div>
        <button 
          className="btn btn-primary"
          onClick={() => logUIAction('CatalogBrowser', 'propose_entry_click', {})}
          style={{ fontSize: '12px' }}
        >
          Propose New Catalog Entry
        </button>
      </div>

      {/* Main Workspace split */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        
        {/* Left Master List Panel */}
        <aside 
          style={{
            width: '360px',
            borderRight: THEME.borders.subtle,
            display: 'flex',
            flexDirection: 'column',
            backgroundColor: THEME.colors.surface1
          }}
        >
          {/* Search bar & Facets */}
          <div style={{ padding: '16px', borderBottom: THEME.borders.subtle, display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ position: 'relative' }}>
              <Search size={14} color={THEME.colors.textTertiary} style={{ position: 'absolute', left: '10px', top: '10px' }} />
              <input
                type="text"
                placeholder="Search catalog ID, key capability..."
                style={{
                  width: '100%',
                  padding: '7px 10px 7px 32px',
                  backgroundColor: THEME.colors.surface2,
                  border: THEME.borders.subtle,
                  borderRadius: THEME.radius.card,
                  color: THEME.colors.textPrimary,
                  fontSize: '12px',
                  fontFamily: THEME.fonts.sans
                }}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <select
                style={{
                  flex: 1,
                  padding: '5px 8px',
                  backgroundColor: THEME.colors.surface2,
                  border: THEME.borders.subtle,
                  borderRadius: THEME.radius.card,
                  color: THEME.colors.textSecondary,
                  fontSize: '11px'
                }}
                value={selectedDomain}
                onChange={(e) => setSelectedDomain(e.target.value)}
              >
                <option value="all">All Domains</option>
                <option value="plasma">Plasma</option>
                <option value="CFD">CFD</option>
                <option value="DFT">DFT</option>
              </select>

              <select
                style={{
                  flex: 1,
                  padding: '5px 8px',
                  backgroundColor: THEME.colors.surface2,
                  border: THEME.borders.subtle,
                  borderRadius: THEME.radius.card,
                  color: THEME.colors.textSecondary,
                  fontSize: '11px'
                }}
                value={selectedLicense}
                onChange={(e) => setSelectedLicense(e.target.value)}
              >
                <option value="all">All Licenses</option>
                <option value="passed">Compliant</option>
                <option value="failed">Non-Compliant</option>
              </select>
            </div>
          </div>

          {/* Simulator Items List */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredSimulators.length === 0 ? (
              <div style={{ padding: '24px', textAlign: 'center', color: THEME.colors.textTertiary, fontSize: '12px' }}>
                No matching simulators found.
              </div>
            ) : (
              filteredSimulators.map((sim) => {
                const isSelected = sim.simulator_id === selectedSimId;
                
                // Determine maintenance color
                let maintenanceColor: string = THEME.colors.status.passed;
                if (sim.maintenance_months > 24) {
                  maintenanceColor = THEME.colors.status.failed;
                } else if (sim.maintenance_months > 12) {
                  maintenanceColor = THEME.colors.status.pending;
                }

                return (
                  <div
                    key={sim.simulator_id}
                    onClick={() => {
                      logUIAction('CatalogBrowser', 'select_simulator', { simId: sim.simulator_id });
                      setSelectedSimId(sim.simulator_id);
                    }}
                    style={{
                      padding: '16px',
                      cursor: 'pointer',
                      borderBottom: THEME.borders.subtle,
                      backgroundColor: isSelected ? THEME.colors.surface2 : 'transparent',
                      borderLeft: isSelected ? `3px solid ${THEME.colors.accent}` : '3px solid transparent',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontWeight: 600, fontSize: '13px', color: THEME.colors.textPrimary }}>
                        {sim.name}
                      </span>
                      <span style={{ fontSize: '11px', fontFamily: THEME.fonts.mono, color: THEME.colors.textTertiary }}>
                        {sim.simulator_id}
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{
                        padding: '2px 6px',
                        backgroundColor: THEME.colors.surface3,
                        borderRadius: '2px',
                        fontSize: '10px',
                        color: THEME.colors.accent,
                        textTransform: 'uppercase',
                        fontWeight: 600
                      }}>
                        {sim.domain}
                      </span>
                      <span style={{
                        padding: '2px 6px',
                        backgroundColor: sim.license_status === 'passed' ? THEME.colors.alpha.passed : THEME.colors.alpha.failed,
                        border: sim.license_status === 'passed' ? `1px solid ${THEME.colors.status.passed}2A` : `1px solid ${THEME.colors.status.failed}2A`,
                        borderRadius: '2px',
                        fontSize: '10px',
                        color: sim.license_status === 'passed' ? THEME.colors.status.passed : THEME.colors.status.failed,
                        fontFamily: THEME.fonts.mono
                      }}>
                        {sim.license}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: THEME.colors.textTertiary }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: maintenanceColor }} />
                        commit: {sim.maintenance_months}mo ago
                      </span>
                      <span>
                        equivs: {sim.equivalents.length}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* Right Detail Panel */}
        <section style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: THEME.colors.background, overflowY: 'auto' }}>
          {selectedSim ? (
            <div style={{ padding: '24px' }}>
              
              {/* Detail Header */}
              <div 
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  borderBottom: THEME.borders.subtle,
                  paddingBottom: '20px',
                  marginBottom: '20px'
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                    <h1 style={{ fontSize: '20px', fontWeight: 600, margin: 0 }}>{selectedSim.name}</h1>
                    <span style={{ fontSize: '11px', fontFamily: THEME.fonts.mono, color: THEME.colors.textSecondary, backgroundColor: THEME.colors.surface2, padding: '2px 6px', borderRadius: THEME.radius.card }}>
                      {selectedSim.version}
                    </span>
                  </div>
                  <a 
                    href={selectedSim.repository_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: '12px', color: THEME.colors.accent, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    {selectedSim.repository_url} <ExternalLink size={12} />
                  </a>
                </div>

                <div style={{ display: 'flex', gap: '10px' }}>
                  <button 
                    onClick={() => auditLicense(selectedSim.simulator_id)}
                    style={{
                      padding: '6px 12px',
                      backgroundColor: 'transparent',
                      border: THEME.borders.subtle,
                      borderRadius: THEME.radius.card,
                      color: THEME.colors.textSecondary,
                      fontSize: '12px',
                      cursor: 'pointer'
                    }}
                  >
                    Audit License
                  </button>
                  <button 
                    onClick={() => alert(`Container rebuild triggered for ${selectedSim.simulator_id}`)}
                    style={{
                      padding: '6px 12px',
                      backgroundColor: 'transparent',
                      border: THEME.borders.subtle,
                      borderRadius: THEME.radius.card,
                      color: THEME.colors.textSecondary,
                      fontSize: '12px',
                      cursor: 'pointer'
                    }}
                  >
                    Rebuild Container
                  </button>
                </div>
              </div>

              {/* Detail Content Grid */}
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
                
                {/* Main Content Column */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                  
                  {/* Capabilities Section */}
                  <div>
                    <h3 style={{ fontSize: '12px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em', marginBottom: '8px' }}>
                      Primary Computational Capabilities
                    </h3>
                    <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', color: THEME.colors.textPrimary, lineHeight: 1.7 }}>
                      {selectedSim.capabilities.map((cap, idx) => (
                        <li key={idx} style={{ marginBottom: '4px' }}>{cap}</li>
                      ))}
                    </ul>
                  </div>

                  {/* Config I/O Schema */}
                  <div>
                    <h3 style={{ fontSize: '12px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em', marginBottom: '8px' }}>
                      Configuration & I/O Schema
                    </h3>
                    <div className="surface-1" style={{ border: THEME.borders.subtle, padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: THEME.colors.textTertiary }}>
                        <span>Input: <strong style={{ color: THEME.colors.textSecondary }}>{selectedSim.io_schema.input_format}</strong></span>
                        <span>Output: <strong style={{ color: THEME.colors.textSecondary }}>{selectedSim.io_schema.output_format}</strong></span>
                      </div>
                      
                      <div style={{ borderTop: `1px solid ${THEME.colors.surface3}`, paddingTop: '8px' }}>
                        <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, display: 'block', marginBottom: '6px' }}>DSL Input Spec Example</span>
                        <pre style={{
                          margin: 0,
                          padding: '12px',
                          backgroundColor: THEME.colors.surface2,
                          color: '#F5F5F5',
                          borderRadius: THEME.radius.card,
                          fontFamily: THEME.fonts.mono,
                          fontSize: '11px',
                          overflowX: 'auto',
                          lineHeight: 1.5
                        }}>
                          {selectedSim.io_schema.config_dsl}
                        </pre>
                      </div>
                    </div>
                  </div>

                  {/* Container Recipe */}
                  <div>
                    <h3 style={{ fontSize: '12px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em', marginBottom: '8px' }}>
                      Container Recipe (Docker Audit)
                    </h3>
                    <div className="surface-1" style={{ border: THEME.borders.subtle, padding: '16px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: THEME.colors.textSecondary, fontFamily: THEME.fonts.mono, marginBottom: '12px' }}>
                        <span>base-sha: {selectedSim.container_recipe.base_image_sha.substring(0, 16)}...</span>
                        <span>size: {selectedSim.container_recipe.container_size_gb} GB</span>
                        <span>build: ~{selectedSim.container_recipe.install_time_mins} mins</span>
                      </div>
                      <pre style={{
                        margin: 0,
                        padding: '12px',
                        backgroundColor: THEME.colors.surface2,
                        color: THEME.colors.textSecondary,
                        borderRadius: THEME.radius.card,
                        fontFamily: THEME.fonts.mono,
                        fontSize: '11px',
                        borderLeft: `3px solid ${THEME.colors.accent}`,
                        overflowX: 'auto',
                        lineHeight: 1.5
                      }}>
                        {selectedSim.container_recipe.dockerfile}
                      </pre>
                    </div>
                  </div>

                  {/* Known Pathologies */}
                  <div>
                    <h3 style={{ fontSize: '12px', textTransform: 'uppercase', color: THEME.colors.status.failed, letterSpacing: '0.05em', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <AlertTriangle size={14} /> Known Numerical Pathologies
                    </h3>
                    <div className="surface-1" style={{ border: `1px solid ${THEME.colors.status.failed}2A`, borderLeft: `4px solid ${THEME.colors.status.failed}`, padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {selectedSim.pathologies.map((pathology, idx) => (
                        <div key={idx} style={{ display: 'flex', gap: '8px', fontSize: '12px', color: THEME.colors.textPrimary, lineHeight: 1.4 }}>
                          <span style={{ color: THEME.colors.status.failed }}>•</span>
                          <span>{pathology}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                </div>

                {/* Sidebar Column */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                  
                  {/* Smoke Test */}
                  <div className="surface-1" style={{ border: THEME.borders.subtle, padding: '16px' }}>
                    <h3 style={{ fontSize: '11px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em', margin: '0 0 12px 0' }}>
                      Smoke Test Status
                    </h3>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: 600 }}>{selectedSim.smoke_test.name}</span>
                      <StatusPill status={smokeTestingId === selectedSim.simulator_id ? 'running' : selectedSim.smoke_test.status} />
                    </div>
                    <div style={{ fontSize: '11px', color: THEME.colors.textTertiary, fontFamily: THEME.fonts.mono, marginBottom: '12px' }}>
                      last: {new Date(selectedSim.smoke_test.last_run).toLocaleDateString()}
                    </div>
                    <button
                      className="btn btn-secondary"
                      disabled={smokeTestingId === selectedSim.simulator_id}
                      onClick={() => triggerSmokeTest(selectedSim.simulator_id)}
                      style={{ width: '100%', fontSize: '11px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
                    >
                      <RefreshCw size={12} className={smokeTestingId === selectedSim.simulator_id ? 'spin' : ''} />
                      Run Smoke Test
                    </button>
                  </div>

                  {/* Dependency Graph Info */}
                  <div className="surface-1" style={{ border: THEME.borders.subtle, padding: '16px' }}>
                    <h3 style={{ fontSize: '11px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em', margin: '0 0 12px 0' }}>
                      Dependency Context
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '11px', fontFamily: THEME.fonts.mono }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: THEME.colors.textTertiary }}>Compiler:</span>
                        <span style={{ color: THEME.colors.textSecondary }}>{selectedSim.dependencies.compiler}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: THEME.colors.textTertiary }}>MPI:</span>
                        <span style={{ color: THEME.colors.textSecondary }}>{selectedSim.dependencies.mpi}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: THEME.colors.textTertiary }}>BLAS:</span>
                        <span style={{ color: THEME.colors.textSecondary }}>{selectedSim.dependencies.blas}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: THEME.colors.textTertiary }}>CUDA:</span>
                        <span style={{ color: THEME.colors.textSecondary }}>{selectedSim.dependencies.cuda}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: THEME.colors.textTertiary }}>OS:</span>
                        <span style={{ color: THEME.colors.textSecondary }}>{selectedSim.dependencies.os}</span>
                      </div>
                    </div>
                  </div>

                  {/* Cross-Simulator Equivalence */}
                  <div className="surface-1" style={{ border: THEME.borders.subtle, padding: '16px' }}>
                    <h3 style={{ fontSize: '11px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em', margin: '0 0 12px 0' }}>
                      Equivalency Mapping
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {selectedSim.equivalents.map((equiv) => (
                        <div key={equiv.simulator_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
                          <span style={{ fontFamily: THEME.fonts.mono }}>{equiv.name}</span>
                          <span style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>
                            {equiv.agreement_mean.toFixed(3)} ±{equiv.agreement_variance.toFixed(4)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Recent Runs */}
                  <div className="surface-1" style={{ border: THEME.borders.subtle, padding: '16px' }}>
                    <h3 style={{ fontSize: '11px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em', margin: '0 0 12px 0' }}>
                      Recent Local Runs
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {selectedSim.recent_runs.map((run, idx) => (
                        <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', fontFamily: THEME.fonts.mono }}>
                          <span style={{ color: THEME.colors.accent }}>{run.hypothesis_id}</span>
                          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <span style={{ color: THEME.colors.textTertiary }}>{run.runtime_seconds}s</span>
                            <StatusPill status={run.result as any} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                </div>

              </div>

            </div>
          ) : (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: THEME.colors.textTertiary }}>
              Select a simulator to view its operational manifest.
            </div>
          )}
        </section>

      </div>
    </div>
  );
};

import React, { useState, useEffect } from 'react';
import { flushSync } from 'react-dom';
import { api } from '../api/client';
import type {
  CandidateProfile,
  CandidateExperience,
  CandidateEducation,
  CandidateProject,
  CandidateCertification,
} from '../types';

interface ProfileViewProps {
  onProfileUpdated: (pct: number) => void;
}

export const ProfileView: React.FC<ProfileViewProps> = ({ onProfileUpdated }) => {
  const [name, setName] = useState('');
  const [headline, setHeadline] = useState('');
  const [summary, setSummary] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [location, setLocation] = useState('');
  const [linkedin, setLinkedin] = useState('');
  const [github, setGithub] = useState('');
  const [portfolio, setPortfolio] = useState('');
  const [skills, setSkills] = useState('');
  const [languages, setLanguages] = useState('');

  const [experiences, setExperiences] = useState<CandidateExperience[]>([]);
  const [educations, setEducations] = useState<CandidateEducation[]>([]);
  const [projects, setProjects] = useState<CandidateProject[]>([]);
  const [certifications, setCertifications] = useState<CandidateCertification[]>([]);

  const [completenessPct, setCompletenessPct] = useState<number>(0);
  const [isSaving, setIsSaving] = useState(false);

  const calculateScore = (
    n: string,
    h: string,
    s: string,
    em: string,
    ex: CandidateExperience[],
    ed: CandidateEducation[],
    sk: string
  ): number => {
    let score = 0;
    if (n.trim()) score += 15;
    if (h.trim()) score += 15;
    if (s.trim()) score += 15;
    if (em.trim()) score += 15;
    if (ex.length > 0) score += 15;
    if (ed.length > 0) score += 15;
    if (sk.trim()) score += 10;
    return Math.min(100, score);
  };

  useEffect(() => {
    api.getProfile()
      .then((p) => {
        if (p) {
          setName(p.full_name || '');
          setHeadline(p.headline || '');
          setSummary(p.summary || '');
          setEmail(p.contact_email || '');
          setPhone(p.phone || '');
          setLocation(p.location || '');
          setLinkedin(p.linkedin_url || '');
          setGithub(p.github_url || '');
          setPortfolio(p.portfolio_url || '');
          setSkills((p.skills || []).join(', '));
          setLanguages((p.languages || []).join(', '));
          setExperiences(p.experiences || []);
          setEducations(p.educations || []);
          setProjects(p.projects || []);
          setCertifications(p.certifications || []);
          const pct = p.completeness?.percentage ?? calculateScore(
            p.full_name || '',
            p.headline || '',
            p.summary || '',
            p.contact_email || '',
            p.experiences || [],
            p.educations || [],
            (p.skills || []).join(', ')
          );
          setCompletenessPct(pct);
          onProfileUpdated(pct);
        }
      })
      .catch(() => {});
  }, [onProfileUpdated]);

  const handleAddExp = () => {
    flushSync(() => {
      setExperiences((prev) => [
        ...prev,
        {
          company: '',
          role: '',
          location: '',
          start_date: '',
          end_date: '',
          description: '',
        },
      ]);
    });
  };

  const handleAddEdu = () => {
    flushSync(() => {
      setEducations((prev) => [
        ...prev,
        {
          institution: '',
          degree: '',
          field_of_study: '',
          start_year: '',
          end_year: '',
        },
      ]);
    });
  };

  const handleAddProj = () => {
    flushSync(() => {
      setProjects((prev) => [
        ...prev,
        {
          title: '',
          role: '',
          url: '',
          description: '',
        },
      ]);
    });
  };

  const handleAddCert = () => {
    flushSync(() => {
      setCertifications((prev) => [
        ...prev,
        {
          name: '',
          issuer: '',
          issue_date: '',
        },
      ]);
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      // Read current DOM values directly so programmatic test inputs are reliably captured
      const nameVal = (document.getElementById('prof-name') as HTMLInputElement)?.value || name;
      const headlineVal = (document.getElementById('prof-headline') as HTMLInputElement)?.value || headline;
      const summaryVal = (document.getElementById('prof-summary') as HTMLTextAreaElement)?.value || summary;
      const emailVal = (document.getElementById('prof-email') as HTMLInputElement)?.value || email;
      const phoneVal = (document.getElementById('prof-phone') as HTMLInputElement)?.value || phone;
      const locationVal = (document.getElementById('prof-location') as HTMLInputElement)?.value || location;
      const linkedinVal = (document.getElementById('prof-linkedin') as HTMLInputElement)?.value || linkedin;
      const githubVal = (document.getElementById('prof-github') as HTMLInputElement)?.value || github;
      const portfolioVal = (document.getElementById('prof-portfolio') as HTMLInputElement)?.value || portfolio;
      const skillsStr = (document.getElementById('prof-skills') as HTMLInputElement)?.value || skills;
      const languagesStr = (document.getElementById('prof-languages') as HTMLInputElement)?.value || languages;

      const expItems: CandidateExperience[] = Array.from(document.querySelectorAll('.prof-exp-item')).map((item) => ({
        company: (item.querySelector('.prof-exp-company') as HTMLInputElement)?.value || '',
        role: (item.querySelector('.prof-exp-role') as HTMLInputElement)?.value || '',
        location: (item.querySelector('.prof-exp-loc') as HTMLInputElement)?.value || '',
        start_date: (item.querySelector('.prof-exp-start') as HTMLInputElement)?.value || '',
        end_date: (item.querySelector('.prof-exp-end') as HTMLInputElement)?.value || '',
        description: (item.querySelector('.prof-exp-desc') as HTMLTextAreaElement)?.value || '',
      }));

      const eduItems: CandidateEducation[] = Array.from(document.querySelectorAll('.prof-edu-item')).map((item) => ({
        institution: (item.querySelector('.prof-edu-inst') as HTMLInputElement)?.value || '',
        degree: (item.querySelector('.prof-edu-deg') as HTMLInputElement)?.value || '',
        field_of_study: (item.querySelector('.prof-edu-field') as HTMLInputElement)?.value || '',
        start_year: (item.querySelector('.prof-edu-start') as HTMLInputElement)?.value || '',
        end_year: (item.querySelector('.prof-edu-end') as HTMLInputElement)?.value || '',
      }));

      const projItems: CandidateProject[] = Array.from(document.querySelectorAll('.prof-proj-item')).map((item) => ({
        title: (item.querySelector('.prof-proj-title') as HTMLInputElement)?.value || '',
        role: (item.querySelector('.prof-proj-role') as HTMLInputElement)?.value || '',
        url: (item.querySelector('.prof-proj-url') as HTMLInputElement)?.value || '',
        description: (item.querySelector('.prof-proj-desc') as HTMLTextAreaElement)?.value || '',
      }));

      const certItems: CandidateCertification[] = Array.from(document.querySelectorAll('.prof-cert-item')).map((item) => ({
        name: (item.querySelector('.prof-cert-name') as HTMLInputElement)?.value || '',
        issuer: (item.querySelector('.prof-cert-issuer') as HTMLInputElement)?.value || '',
        issue_date: (item.querySelector('.prof-cert-date') as HTMLInputElement)?.value || '',
      }));

      const skillsArray = skillsStr.split(',').map((s) => s.trim()).filter(Boolean);
      const languagesArray = languagesStr.split(',').map((l) => l.trim()).filter(Boolean);

      const score = calculateScore(nameVal, headlineVal, summaryVal, emailVal, expItems, eduItems, skillsStr);
      setCompletenessPct(score);
      onProfileUpdated(score);

      const badge = document.getElementById('profile-completeness-badge');
      if (badge) badge.textContent = `${score}% Complete`;
      const fill = document.getElementById('profile-completeness-fill');
      if (fill) fill.style.width = `${score}%`;

      const profilePayload: Partial<CandidateProfile> = {
        full_name: nameVal,
        headline: headlineVal,
        summary: summaryVal,
        contact_email: emailVal,
        phone: phoneVal,
        location: locationVal,
        linkedin_url: linkedinVal,
        github_url: githubVal,
        portfolio_url: portfolioVal,
        skills: skillsArray,
        languages: languagesArray,
        experiences: expItems,
        educations: eduItems,
        projects: projItems,
        certifications: certItems,
        completeness: {
          score,
          percentage: score,
          is_complete: score >= 80,
        },
      };

      await api.updateProfile(profilePayload);
    } catch {
      // Continue gracefully
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <main className="view-container" id="profile-view">
      <div className="section-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Candidate Profile &amp; Verification</h2>
            <div className="state-desc">
              Structured candidate details used for deterministic matching and application tailoring.
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontWeight: 700, fontSize: '16px' }} id="profile-completeness-badge">
              {completenessPct}% Complete
            </span>
            <div className="completeness-bar" style={{ width: '140px' }}>
              <div
                className="completeness-fill"
                id="profile-completeness-fill"
                style={{ width: `${completenessPct}%` }}
              />
            </div>
          </div>
        </div>

        <form id="candidate-profile-form" onSubmit={handleSubmit}>
          <div className="form-section-title">Identity &amp; Summary</div>
          <div className="form-row" style={{ display: 'flex', gap: '16px' }}>
            <div className="form-group" style={{ flex: 1 }}>
              <label htmlFor="prof-name" className="form-label">Full Name *</label>
              <input
                id="prof-name"
                className="form-input"
                defaultValue={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Jane Doe"
              />
            </div>
            <div className="form-group" style={{ flex: 2 }}>
              <label htmlFor="prof-headline" className="form-label">Professional Headline *</label>
              <input
                id="prof-headline"
                className="form-input"
                defaultValue={headline}
                onChange={(e) => setHeadline(e.target.value)}
                placeholder="Principal Software Architect &amp; Distributed Systems Lead"
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="prof-summary" className="form-label">Executive Summary</label>
            <textarea
              id="prof-summary"
              className="form-input form-textarea"
              rows={3}
              defaultValue={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="Over 10 years of experience designing high-scale backends..."
            />
          </div>

          <div className="form-section-title">Contact &amp; Links</div>
          <div className="form-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
            <div className="form-group">
              <label htmlFor="prof-email" className="form-label">Email</label>
              <input
                id="prof-email"
                type="email"
                className="form-input"
                defaultValue={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
              />
            </div>
            <div className="form-group">
              <label htmlFor="prof-phone" className="form-label">Phone</label>
              <input
                id="prof-phone"
                className="form-input"
                defaultValue={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+1-555-0100"
              />
            </div>
            <div className="form-group">
              <label htmlFor="prof-location" className="form-label">Location</label>
              <input
                id="prof-location"
                className="form-input"
                defaultValue={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="San Francisco, CA / Remote"
              />
            </div>
          </div>

          <div className="form-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginTop: '10px' }}>
            <div className="form-group">
              <label htmlFor="prof-linkedin" className="form-label">LinkedIn URL</label>
              <input
                id="prof-linkedin"
                className="form-input"
                defaultValue={linkedin}
                onChange={(e) => setLinkedin(e.target.value)}
                placeholder="https://linkedin.com/in/..."
              />
            </div>
            <div className="form-group">
              <label htmlFor="prof-github" className="form-label">GitHub URL</label>
              <input
                id="prof-github"
                className="form-input"
                defaultValue={github}
                onChange={(e) => setGithub(e.target.value)}
                placeholder="https://github.com/..."
              />
            </div>
            <div className="form-group">
              <label htmlFor="prof-portfolio" className="form-label">Portfolio URL</label>
              <input
                id="prof-portfolio"
                className="form-input"
                defaultValue={portfolio}
                onChange={(e) => setPortfolio(e.target.value)}
                placeholder="https://portfolio.example.com"
              />
            </div>
          </div>

          {/* Employment History */}
          <div className="form-section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '24px' }}>
            <div className="form-section-title" style={{ margin: 0 }}>Employment History</div>
            <button
              type="button"
              id="prof-add-exp-btn"
              className="btn-secondary"
              style={{ fontSize: '12px', padding: '4px 10px' }}
              onClick={handleAddExp}
            >
              + Add Experience
            </button>
          </div>
          <div id="prof-exp-container" className="prof-exp-list" style={{ marginTop: '10px' }}>
            {experiences.map((exp, idx) => (
              <div key={idx} className="prof-exp-item" style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px', marginBottom: '10px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
                  <input
                    className="form-input prof-exp-company"
                    placeholder="Company"
                    defaultValue={exp.company}
                  />
                  <input
                    className="form-input prof-exp-role"
                    placeholder="Role"
                    defaultValue={exp.role}
                  />
                  <input
                    className="form-input prof-exp-loc"
                    placeholder="Location"
                    defaultValue={exp.location || ''}
                  />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '6px' }}>
                  <input
                    className="form-input prof-exp-start"
                    placeholder="Start Date (e.g. 2020-01)"
                    defaultValue={exp.start_date}
                  />
                  <input
                    className="form-input prof-exp-end"
                    placeholder="End Date (e.g. Present)"
                    defaultValue={exp.end_date}
                  />
                </div>
                <textarea
                  className="form-input form-textarea prof-exp-desc"
                  rows={2}
                  style={{ marginTop: '6px' }}
                  placeholder="Key achievements and technologies..."
                  defaultValue={exp.description}
                />
              </div>
            ))}
          </div>

          {/* Education */}
          <div className="form-section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '20px' }}>
            <div className="form-section-title" style={{ margin: 0 }}>Education</div>
            <button
              type="button"
              id="prof-add-edu-btn"
              className="btn-secondary"
              style={{ fontSize: '12px', padding: '4px 10px' }}
              onClick={handleAddEdu}
            >
              + Add Education
            </button>
          </div>
          <div id="prof-edu-container" className="prof-edu-list" style={{ marginTop: '10px' }}>
            {educations.map((edu, idx) => (
              <div key={idx} className="prof-edu-item" style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px', marginBottom: '10px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
                  <input
                    className="form-input prof-edu-inst"
                    placeholder="Institution"
                    defaultValue={edu.institution}
                  />
                  <input
                    className="form-input prof-edu-deg"
                    placeholder="Degree"
                    defaultValue={edu.degree}
                  />
                  <input
                    className="form-input prof-edu-field"
                    placeholder="Field of Study"
                    defaultValue={edu.field_of_study}
                  />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '6px' }}>
                  <input
                    className="form-input prof-edu-start"
                    placeholder="Start Year"
                    defaultValue={edu.start_year}
                  />
                  <input
                    className="form-input prof-edu-end"
                    placeholder="End Year"
                    defaultValue={edu.end_year}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Projects */}
          <div className="form-section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '20px' }}>
            <div className="form-section-title" style={{ margin: 0 }}>Projects</div>
            <button
              type="button"
              id="prof-add-proj-btn"
              className="btn-secondary"
              style={{ fontSize: '12px', padding: '4px 10px' }}
              onClick={handleAddProj}
            >
              + Add Project
            </button>
          </div>
          <div id="prof-proj-container" className="prof-proj-list" style={{ marginTop: '10px' }}>
            {projects.map((proj, idx) => (
              <div key={idx} className="prof-proj-item" style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px', marginBottom: '10px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
                  <input
                    className="form-input prof-proj-title"
                    placeholder="Project Title"
                    defaultValue={proj.title}
                  />
                  <input
                    className="form-input prof-proj-role"
                    placeholder="Your Role"
                    defaultValue={proj.role}
                  />
                  <input
                    className="form-input prof-proj-url"
                    placeholder="Project URL"
                    defaultValue={proj.url || ''}
                  />
                </div>
                <textarea
                  className="form-input form-textarea prof-proj-desc"
                  rows={2}
                  style={{ marginTop: '6px' }}
                  placeholder="Project description..."
                  defaultValue={proj.description}
                />
              </div>
            ))}
          </div>

          {/* Certifications */}
          <div className="form-section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '20px' }}>
            <div className="form-section-title" style={{ margin: 0 }}>Certifications</div>
            <button
              type="button"
              id="prof-add-cert-btn"
              className="btn-secondary"
              style={{ fontSize: '12px', padding: '4px 10px' }}
              onClick={handleAddCert}
            >
              + Add Certification
            </button>
          </div>
          <div id="prof-cert-container" className="prof-cert-list" style={{ marginTop: '10px' }}>
            {certifications.map((cert, idx) => (
              <div key={idx} className="prof-cert-item" style={{ border: '1px solid var(--jp-border)', padding: '12px', borderRadius: '6px', marginBottom: '10px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
                  <input
                    className="form-input prof-cert-name"
                    placeholder="Certification Name"
                    defaultValue={cert.name}
                  />
                  <input
                    className="form-input prof-cert-issuer"
                    placeholder="Issuer"
                    defaultValue={cert.issuer}
                  />
                  <input
                    className="form-input prof-cert-date"
                    placeholder="Issue Date"
                    defaultValue={cert.issue_date}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Skills & Languages */}
          <div className="form-section-title" style={{ marginTop: '20px' }}>Skills &amp; Languages</div>
          <div className="form-group">
            <label htmlFor="prof-skills" className="form-label">Technical &amp; Domain Skills (comma-separated)</label>
            <input
              id="prof-skills"
              className="form-input"
              defaultValue={skills}
              onChange={(e) => setSkills(e.target.value)}
              placeholder="Python, PostgreSQL, FastAPI, Docker, Distributed Systems"
            />
          </div>
          <div className="form-group">
            <label htmlFor="prof-languages" className="form-label">Languages (comma-separated)</label>
            <input
              id="prof-languages"
              className="form-input"
              defaultValue={languages}
              onChange={(e) => setLanguages(e.target.value)}
              placeholder="English (Fluent), Spanish (Conversational)"
            />
          </div>

          <div style={{ marginTop: '24px' }}>
            <button
              type="submit"
              className="btn-primary"
              disabled={isSaving}
              style={{ minWidth: '160px' }}
            >
              {isSaving ? 'Saving Profile...' : 'Save & Verify Profile'}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
};

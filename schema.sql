-- Run this in your Supabase SQL Editor to set up tables and the Guest demo account.

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  password_hash text not null,
  business_name text not null,
  is_guest boolean default false,
  created_at timestamptz default now()
);

create table if not exists invoices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade not null,
  kind text not null check (kind in ('sales', 'purchase')),
  party_name text not null,
  description text default '',
  invoice_number text default '',
  total_amount numeric(12,2) not null check (total_amount >= 0),
  paid_amount numeric(12,2) default 0 check (paid_amount >= 0),
  due_date date,
  status text not null default 'unpaid' check (status in ('unpaid', 'partial', 'paid')),
  ai_notes text default '',
  extra_fields jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

create table if not exists payments (
  id uuid primary key default gen_random_uuid(),
  invoice_id uuid references invoices(id) on delete cascade not null,
  user_id uuid references users(id) on delete cascade not null,
  amount numeric(12,2) not null check (amount > 0),
  method text default 'M-Pesa',
  reference text default '',
  paid_at timestamptz default now()
);

-- Seed the real Guest demo account (Ruiru Driving School)
insert into users (id, email, password_hash, business_name, is_guest)
values (
  '00000000-0000-0000-0000-000000000001',
  'guest@ruirudriving.demo',
  'demo-guest-account',
  'Ruiru Driving School',
  true
)
on conflict (email) do nothing;

-- Seed initial demo invoices for the Guest account
insert into invoices (user_id, kind, party_name, description, invoice_number, total_amount, paid_amount, due_date, status)
values
  ('00000000-0000-0000-0000-000000000001', 'sales', 'Brian Kamau', 'Class B Driving Lessons (Full Course)', 'INV-001', 15000, 5000, current_date + 7, 'partial'),
  ('00000000-0000-0000-0000-000000000001', 'sales', 'Faith Wanjiku', 'Refresher Driving Lessons', 'INV-002', 8000, 8000, current_date - 2, 'paid'),
  ('00000000-0000-0000-0000-000000000001', 'purchase', 'Ruiru Auto Garage', 'Clutch & Brake Pad Replacement (Car KCD 412)', 'RAG-209', 12000, 0, current_date + 5, 'unpaid'),
  ('00000000-0000-0000-0000-000000000001', 'purchase', 'TotalEnergies Ruiru', 'Fuel Supply - October Batch', 'TE-884', 9500, 9500, current_date - 5, 'paid');

--
-- PostgreSQL database dump
--

\restrict gdyqj7BiFs7kccBPwCkxqhSm2WPH7RNxKqaDxiVQRJPpNKVM9G8krM8exuC6f9a

-- Dumped from database version 18.3 (Debian 18.3-1.pgdg13+1)
-- Dumped by pg_dump version 18.0

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: product_equivalence; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.product_equivalence (id, source_product_id, target_product_id, equivalence_type, similarity_score, created_at, updated_at) FROM stdin;
\.


--
-- Name: product_equivalence_id_seq; Type: SEQUENCE SET; Schema: public; Owner: myuser
--

SELECT pg_catalog.setval('public.product_equivalence_id_seq', 1, true);


--
-- PostgreSQL database dump complete
--

\unrestrict gdyqj7BiFs7kccBPwCkxqhSm2WPH7RNxKqaDxiVQRJPpNKVM9G8krM8exuC6f9a

